import calendar
import cgi # parsing form input from /now
from datetime import datetime, timedelta
import logging # DEBUG, INFO, WARNING, ERROR, CRITICAL
import os # for setting timezone
import pprint # for debugging print out
import random # for testing only
import re # for matching email addresses
import string # for ascii_lowercase (testing only)
import time

from google.appengine.ext import db
from google.appengine.api import taskqueue # for checkout sync requests
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

# local imports
import spmdb
import spmemail
import spmcheckout
import spmbuilder
import spmuser
from spmutil import *


################################################################################


class AppPage_Debug(webapp.RequestHandler):


  def __init__(self):
    self._TITLE = 'debug'


  def get(self):
    """Publicly visible debug page.  Make sure requests here are limited to current user."""

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUserByLoggedInGoogleAccount(users.get_current_user())
    if users.is_current_user_admin():
      sudo_as = self.request.get('sudo')
      if sudo_as:
        sudo_user = user_manager.GetSPMUserByEmail(sudo_as, create_new = False)
        if sudo_user:
          spm_loggedin_user = sudo_user
    if not spm_loggedin_user:
      self.redirect('/')
      return

    ### always print ###

    pp = pprint.PrettyPrinter()
    outbuf = ['<body><pre>']
    outbuf.append('Path      [' + self.request.path + ']')
    outbuf.append('Query     [' + self.request.query + ']')
    outbuf.append('User Key  [' + str(spm_loggedin_user.key()) + ']')
    outbuf.append('\n===USER===\n')
    outbuf.append(str(spm_loggedin_user))
    outbuf.append('===USER===')
    outbuf.append('\nFYI, valid paths are:')
    outbuf.append('  /debug/force?days=1 to force a checkout sync')
    outbuf.append('  /debug/dump?days=1 to see raw checkout api response')  

    ### functional things ###

    if self.request.path == '/debug/force' && spm_loggedin_user.checkout_verified:
      sync_value = self.request.get('days')
      if not sync_value:
        sync_value = 180
      else:
        sync_value = long(sync_value)
      outbuf.append('Starting background task to sync ' + str(sync_value) + ' days.')
      # TODO: move this to a background cron job or user-facing button
      taskqueue.add(queue_name='syncqueue', url='/task/checkout', params={
        'user_key': spm_loggedin_user.key(),
        'sync_value': sync_value,
      })
  
    elif self.request.path == '/debug/dump' && spm_loggedin_user.checkout_verified:
      sync_value = self.request.get('days')
      if not sync_value:
        sync_value = 1
      else:
        sync_value = long(sync_value)
      right_now = datetime.utcnow() + timedelta(minutes = -6)      
      start_time = right_now + timedelta(days = (sync_value*-1))
      if start_time < right_now:
        checkout = spmcheckout.CheckoutSellerIntegration(spm_loggedin_user)
        history = checkout.GetHistory(
          utc_start = start_time,
          utc_end = right_now
        )
      outbuf.append(pp.pformat(history))
  
    outbuf.append('</pre></body>')
    self.response.out.write('\n'.join(outbuf))


################################################################################


class TaskPage_SyncCheckout(webapp.RequestHandler):
  """Runs sync checkout in the background.
  Admin only access (app.yaml)"""

  def post(self):

    user_key = self.request.get('user_key')
    spm_user_to_run = db.get(user_key)
    sync_value = long(self.request.get('sync_value'))
    
    logging.debug('Task SyncCheckout user_key ' + user_key)
    logging.debug('Task SyncCheckout sync_value ' + str(sync_value))

    if not spm_user_to_run or not sync_value:
      return

    right_now = datetime.utcnow() + timedelta(minutes = -6)      
    start_time = right_now + timedelta(days = (sync_value*-1))
    if start_time < right_now:
      checkout = spmcheckout.CheckoutSellerIntegration(spm_user_to_run)
      checkout.GetHistory(
        utc_start = start_time,
        utc_end = right_now
      )


class TaskPage_SyncCron(webapp.RequestHandler):
  """Runs sync checkout in the background for all checkout_verified.
  Admin only access (app.yaml)"""

  def get(self):

    logging.debug('Task SyncCron starting')
    userlist = db.GqlQuery(
      'SELECT * FROM SPMUser WHERE checkout_verified = TRUE'
    )
    for user in userlist:
      taskqueue.add(queue_name='syncqueue', url='/task/checkout', params={
        'user_key': user.key(),
        'sync_value': 1,
      })


################################################################################


class AppPage_DefaultRedirect(webapp.RequestHandler):
  def get(self):
    self.redirect("/")


class AppPage_SignoutRedirect(webapp.RequestHandler):
  def get(self):
    self.redirect(users.create_logout_url('/'))


class AppPage_SigninRedirect(webapp.RequestHandler):
  def get(self):
    self.redirect(users.create_login_url('/'))


class AppPage_Default(webapp.RequestHandler):

  def __init__(self):
    self._TITLE = SPM

  def get(self):
    """Returns main page."""

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUserByLoggedInGoogleAccount(users.get_current_user())
    if users.is_current_user_admin():
      sudo_as = self.request.get('sudo')
      if sudo_as:
        sudo_user = user_manager.GetSPMUserByEmail(sudo_as, create_new = False)
        if sudo_user:
          spm_loggedin_user = sudo_user

    ### render page ###

    page = spmbuilder.NewPage(
      title = self._TITLE,
      user = spm_loggedin_user,
      useragent = self.request.headers.get('user_agent'),
      uideb = self.request.get('uideb'),
    )

    if spm_loggedin_user:
      page.AppendSpaced('Logged in, so go to <a href="/everything">everything</a> or <a href="/now">send now</a>.')
    else:
      page.AppendSpaced('Not logged in.  You should <a href="/signin">sign in</a>.')

    self.response.out.write(page.Render())


class AppPage_Send(webapp.RequestHandler):
  """Checkout account required."""


  def __ReserveNextSerialsTransaction(self, spm_name, number_to_reserve):
    """ Run this function as a transaction.  Reserves the next serial numbers."""

    count_record = None
    count_records = db.GqlQuery(
      'SELECT * FROM CountStore WHERE ANCESTOR IS :1',
      db.Key.from_path('CountURL', spm_name)
    ).fetch(limit=2)
    if len(count_records) == 1:
      count_record = count_records[0]
    elif len(count_records) >= 2:
      logging.critical('More than one record returned from ancestor query')

    if count_record:
      cur_count = count_record.url_count
      count_record.url_count = cur_count + number_to_reserve
      count_record.put()
      return cur_count
    else:
      new_record = spmdb.CountStore(
        parent = db.Key.from_path('CountURL', spm_name),
        url_count = number_to_reserve
      )
      new_record.put()
      return 0


  def __init__(self):
    self._TITLE = SPM + ' now'


  def get(self):

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUserByLoggedInGoogleAccount(users.get_current_user())
    if users.is_current_user_admin():
      sudo_as = self.request.get('sudo')
      if sudo_as:
        sudo_user = user_manager.GetSPMUserByEmail(sudo_as, create_new = False)
        if sudo_user:
          spm_loggedin_user = sudo_user
    if not spm_loggedin_user.checkout_verified:
      self.redirect('/')
      return

    ### render page ###

    _PAGE_CONTENT = \
"""<form action="%(posturl)s" method="post">
  <div>Hey!  You owe me money.</div>
  <div>So, pay me for <input type="text" name="url" value=""/> (no spaces or symbols)</div>
  <div>And in case you don't remember what I'm talking about,<br/>
  here are a few more details to jog your memory:</div>
  <div><input type="text" name="description" value=""/></div>
  <div>&nbsp;</div>
  <div>$ <input type="text" name="amount0" value=""/> to <input type="text" name="email0" value=""/></div>
  <div>$ <input type="text" name="amount1" value=""/> to <input type="text" name="email1" value=""/></div>
  <div>$ <input type="text" name="amount2" value=""/> to <input type="text" name="email2" value=""/></div>
  <div>$ <input type="text" name="amount3" value=""/> to <input type="text" name="email3" value=""/></div>
  <div>$ <input type="text" name="amount4" value=""/> to <input type="text" name="email4" value=""/></div>
  <div>$ <input type="text" name="amount5" value=""/> to <input type="text" name="email5" value=""/></div>
  <div>$ <input type="text" name="amount6" value=""/> to <input type="text" name="email6" value=""/></div>
  <div>$ <input type="text" name="amount7" value=""/> to <input type="text" name="email7" value=""/></div>
  <div>&nbsp;</div>
  <div><input type="submit" value="Send Email" /></div>
</form>"""

    page = spmbuilder.NewPage(
      title = self._TITLE,
      user = spm_loggedin_user,
      useragent = self.request.headers.get('user_agent'),
      uideb = self.request.get('uideb'),
    )

    page.AppendText(_PAGE_CONTENT % {'posturl': self.request.path})
    self.response.out.write(page.Render())


  def post(self):
    """Takes a HTML form post and creates a new expense"""

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUserByLoggedInGoogleAccount(users.get_current_user())
    if users.is_current_user_admin():
      sudo_as = self.request.get('sudo')
      if sudo_as:
        sudo_user = user_manager.GetSPMUserByEmail(sudo_as, create_new = False)
        if sudo_user:
          spm_loggedin_user = sudo_user
    if not spm_loggedin_user.checkout_verified:
      self.redirect('/')
      return

    # TODO: convert to JS/JSON with client side validation logic too

    ##### form content validation #####

    form_url = cgi.escape(self.request.get('url'))
    form_description = cgi.escape(self.request.get('description'))

    form_amount_email_pairs = []
    for i in range(0,7):
      cur_amount = cgi.escape(self.request.get('amount' + str(i)))
      cur_email = cgi.escape(self.request.get('email' + str(i)))
      if cur_amount and cur_email:
        form_amount_email_pairs.append((float(cur_amount), cur_email.strip()))

    # url must be a-z, 0-9... no spaces or characters
    if not form_url.isalnum():
      logging.debug('FormValidator: URL failed.')
      return
      # TODO: user-facing notification in this case
    else:
      newcr_spm_name = str(form_url).lower()

    # don't give a shit what's here, if it's not present, just copy the
    # form_description there instead
    if not form_description:
      newcr_description = form_url
    else:
      newcr_description = str(form_description)

    # simple validation, doesn't catch everything but works for the 99% use case
    _EMAIL_REGEX = '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,4}$'

    # needs to be numbers or decimals
    for form_amount, form_email in form_amount_email_pairs:

      if not form_amount:
        logging.debug('FormValidator: Amount failed')
        return
        # TODO: user-facing notification in this case

      if not form_email:
        logging.debug('FormValidator: Email address empty')
        return
        # TODO: user-facing notification in this case
      else:
        if not re.search(_EMAIL_REGEX, form_email):
          logging.debug('FormValidator: Email address failed regex: ' + email)
          return

    ##### create records and checkout urls for this #####
    
    # reserve id for this
    reserved_url_serial = db.run_in_transaction(
      self.__ReserveNextSerialsTransaction, newcr_spm_name, 1
    )

    item_count = 0
    for newcr_amount, email in form_amount_email_pairs:

      new_pr = spmdb.PurchaseRecord(
        parent = MakeAncestorFromSPMUser(spm_loggedin_user),
        SPMUser_seller = spm_loggedin_user.key()
      )
      new_pr.spm_name = newcr_spm_name
      new_pr.spm_serial = reserved_url_serial
      new_pr.spm_transaction = item_count
      new_pr.amount = '%0.2f' % float(newcr_amount)
      new_pr.currency = 'USD'
      new_pr.description = newcr_description
      new_pr.date_sent = datetime.utcnow()
      new_pr.date_latest = new_pr.date_sent
      new_pr.sent_to_email = email
      new_pr.SPMUser_sentto = um.GetSPMUserByEmail(email)

      spmid = BuildSPMID(
        name = new_pr.spm_name,
        serial = new_pr.spm_serial,
        transaction = new_pr.spm_transaction,
      )
  
      checkout = spmcheckout.CheckoutSellerIntegration(spm_loggedin_user)
      checkout_payurl = checkout.GetPaymentUrl(
        spm_full_id = spmid,
        description = new_pr.description,
        amount = new_pr.amount,
        currency = new_pr.currency,
      )
      new_pr.checkout_payurl = checkout_payurl

      if not checkout_payurl:
        logging.critical('New invoice: GetPaymentUrl failed')
        return None
        # TODO: retry, better error handling, and user-facing notification in this case
    
      # send email
      if spm_loggedin_user.name:
        sender_name = spm_loggedin_user.name
      else:
        sender_name = ''
      emailer = spmemail.SPMEmailManager(
        from_name = sender_name,
        # have to use logged-in users email address or appengine won't send
        from_email = spm_loggedin_user.google_account.email(),
      )
      spm_to_user = um.GetSPMUserByEmail(email)
      emailer.SendEmail(
        to_name = spm_to_user.name,
        to_email = email,
        spm_for = newcr_spm_name,
        spm_url = BuildSPMURL(
          name = new_pr.spm_name,
          serial = new_pr.spm_serial,
        ),
        pay_url = checkout_payurl,
        description = newcr_description,
        amount = new_pr.amount, 
      )

      # commit record - do this last in case anything above fails
      new_pr.put()

      # iterate item count for next thing
      item_count += 1

    ##### redirect #####

    # note that there's a datastore delay so we can't redirect immediately to
    # the pay page, so instead redirect to the seller view page
    self.redirect('/everything')
    


class AppPage_PaymentHistory(webapp.RequestHandler):
  """Checkout account required."""

  def __init__(self):
    self._TITLE = SPM + ' everything'


  def get(self):

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUserByLoggedInGoogleAccount(users.get_current_user())
    if users.is_current_user_admin():
      sudo_as = self.request.get('sudo')
      if sudo_as:
        sudo_user = user_manager.GetSPMUserByEmail(sudo_as, create_new = False)
        if sudo_user:
          spm_loggedin_user = sudo_user
    if not spm_loggedin_user.checkout_verified:
      self.redirect('/')
      return

    ##### preprocessing before rendering page #####

    # query as an iterable instead of fetch so we get all the records
    # TODO: implement paging
    records = db.GqlQuery(
      'SELECT * FROM PurchaseRecord '
      'WHERE SPMUser_seller = :1 '
      'ORDER BY date_latest DESC ',
      spm_loggedin_user
    )

    _OTHER_STRING = 'For other things (invoices not sent with sopay.me)'
    _RECORD_STRING = 'For <strong>%(forpart)s</strong> (<em>%(serialpart)s</em>)'

    # group the records into a dict of lists keyed off of url. to be considered
    # in a grouping, the record must have a c14n url and a valid date_sent set,
    # otherwise stick it into the 'other things' category cause it wasn't sent
    # using sopay.me
    sort_buckets = {}
    time_sort = []
    for record in records:
      key_url = BuildSPMURL(record.spm_name, record.spm_serial, relpath=True)  
      if not key_url:
        key_url = _OTHER_STRING
      else:
        # use split url so we get the nice three-digit formatting for #
        split_url = key_url.split('/') # (''/'for'/'name'/'serial')
        key_url = _RECORD_STRING % ({
          'forpart': split_url[2], 
          'serialpart': split_url[3],
        })
      try:
        sort_buckets[key_url]
      except KeyError:
        sort_buckets[key_url] = []
      sort_buckets[key_url].append(record)


    # sort by the most recent update in each of the buckets, but
    # always sort 'other' last (these are the things not sent with spm)
    list_to_sort = []
    for url in sort_buckets.keys():
      date_max = datetime(1985,9,17)
      if not url == _OTHER_STRING:
        for record in sort_buckets[url]:
          if record.date_latest > date_max:
            date_max = record.date_latest
      list_to_sort.append((date_max, url))
    list_to_sort.sort(reverse = True)

    ##### start rendering page #####

    page = spmbuilder.NewPage(
      title = self._TITLE,
      user = spm_loggedin_user,
      useragent = self.request.headers.get('user_agent'),
      uideb = self.request.get('uideb'),
    )

    page.AppendSpaced(
      'Note that payment updates from Google Checkout may take up to an hour to appear. '
    )

    for date, url_key in list_to_sort:
      page.AppendCompact(url_key)
      for record in sort_buckets[url_key]:
        page.AppendHoverRecord(record = record, linkify = True)

    self.response.out.write(page.Render())


class AppPage_StaticPaylink(webapp.RequestHandler):
  """Accessible without login."""

  def get(self):
    """TODO"""

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUserByLoggedInGoogleAccount(users.get_current_user())
    if users.is_current_user_admin():
      sudo_as = self.request.get('sudo')
      if sudo_as:
        sudo_user = user_manager.GetSPMUserByEmail(sudo_as, create_new = False)
        if sudo_user:
          spm_loggedin_user = sudo_user

    # TODO: acl'ed payments
    # if not spm_loggedin_user.checkout_verified:
    #  self.redirect('/')
    #  return

    ##### preprocessing before rendering page #####

    # validate url
    # forward : if self.request.query_string:
    parsed_url = ParseSPMURL(self.request.path, relpath=True)
    if not parsed_url:
      self.redirect("/")
      return

    # if digit is too short redirect to 3char+
    c14n_url = BuildSPMURL(parsed_url['name'], parsed_url['serial'], relpath=True)
    if not c14n_url == self.request.path:
      self.redirect(c14n_url, permanent=True)
      return
    self._TITLE = SPM + ' for ' + parsed_url['name']

    # query this as an iterable instead of fetch so we get them all
    records = db.GqlQuery(
      'SELECT * FROM PurchaseRecord '
      'WHERE spm_name = :1 AND spm_serial = :2',
      parsed_url['name'], parsed_url['serial']
    )

    ##### start rendering page #####

    records_shown = False

    page = spmbuilder.NewPage(
      title = self._TITLE,
      user = spm_loggedin_user,
      useragent = self.request.headers.get('user_agent'),
      uideb = self.request.get('uideb'),
    )

    page.AppendSpaced(
      'Note that payment updates from Google Checkout may take up to an hour to appear.'
    )

    for record in records:
      records_shown = True
      page.AppendHoverRecord(record = record, linkify = False)

    # if there aren't any records, there's nothing to show
    if not records_shown:
      self.redirect('/')
      return
    else:
      self.response.out.write(page.Render())


################################################################################


application = webapp.WSGIApplication([
  # Background task queues
  ('/task/checkout', TaskPage_SyncCheckout),
  ('/task/synccron', TaskPage_SyncCron),
  # User-facing
  ('/debug.*', AppPage_Debug),
  ('/now', AppPage_Send),
  ('/everything', AppPage_PaymentHistory),
  ('/signout.*', AppPage_SignoutRedirect),
  ('/signin.*', AppPage_SigninRedirect),
  ('/for/.*', AppPage_StaticPaylink),
  # Home page redirect
  ('/', AppPage_Default),
  ('/.*', AppPage_DefaultRedirect),
],debug=True)


def main():
  os.environ['TZ'] = 'US/Pacific'
  time.tzset()
  logging.getLogger().setLevel(logging.DEBUG)
  run_wsgi_app(application)


if __name__ == "__main__":
  main()