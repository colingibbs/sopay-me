import calendar
import cgi # parsing form input from /now
from datetime import datetime, timedelta
import logging # DEBUG, INFO, WARNING, ERROR, CRITICAL
import os # for setting timezone
import pprint # for testing/debugging only
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
import spmuser
from spmutil import *


################################################################################


_PRETTY_TIME = '%B %d'
_YMD_TIME = '%Y-%m-%d'

_PAGE_INLINEERROR =\
"""<div class="lineerror"><strong>ERROR:</strong> %(message)s</div>"""

_PAGE_SIMPLEDIV =\
"""<div class="simple"><strong><em>NOTE:</em></strong> %(message)s</div>"""

_PAGE_INLINE =\
"""<div class="simple">%(message)s</div>"""

pp = pprint.PrettyPrinter(indent=1)


################################################################################


def IsMobile(useragent):
  if 'android' in useragent.lower() or 'iphone' in useragent.lower():
    return True
  else:
    return False


def CreateHeader(title, useragent):

  _PAGE_HEADER = \
"""<!DOCTYPE HTML>
<html>
<head>
\t<meta http-equiv="content-type" content="text/html; charset=utf-8">
\t<title>%(title)s</title>
\t<link rel="stylesheet" type="text/css" href="%(css)s" />
%(additional)s
</head>
<body>
\t<div id="title">%(title)s</div>"""

  _MOBILE_META = \
"""<meta name="HandheldFriendly" content="true" />
<meta name="viewport" content="width=device-width, height=device-height, user-scalable=no" />"""

  if IsMobile(useragent):
    return _PAGE_HEADER % ({
      'title': title,
      'css': '/static/mobile.css',
      'additional': _MOBILE_META,
    })
  else:
    return _PAGE_HEADER % ({
      'title': title,
      'css': '/static/sopayme.css',
      'additional': '',
    })


def CreateFooter():

  _PAGE_FOOTER = \
"""<div class="simple"></div>
</body>
<!-- Copyright 2011 SoPay.Me -->"""

  return _PAGE_FOOTER

  
def CreateHoverLine(record, linkify, useragent):

  outbuf = []

  ##### validate user information #####
  
  if record.SPMUser_sentto:
    if record.sent_to_email:
      text_email = record.sent_to_email
    else:
      text_email = str(record.SPMUser_sentto.email)
    if not text_email:
      text_email = 'ERROR: No email'
    text_seller = record.SPMUser_sentto.name
    if not text_seller:
      text_seller = text_email
    if record.SPMUser_sentto.facebook_id:
      url_seller_picture = 'http://graph.facebook.com/' + record.SPMUser_sentto.facebook_id + '/picture?square'
    else:
      url_seller_picture = ''
  else:
    logging.debug('Trying to render hover line, SPMUser_sentto is none.')
    text_seller = 'ERROR: No user found'
    text_email = 'ERROR: No user found'
    url_seller_picture = ''

  ##### validate record information #####

  c14n_url = BuildSPMURL(record.spm_name, record.spm_serial, relpath=True)

  if record.date_sent:
    text_sent = (
      'Sent on ' + record.date_sent.strftime(_PRETTY_TIME)
      # + ': <a href="' + c14n_url + '">' + c14n_url[1:] + '</a>'
    )
    div_sent = '<div class="icon yes"></div>'
  else:
    # TODO remove if we stop showing old items
    text_sent = '<span class="maybetext">Not from ' + SPM + '</span>'
    div_sent = '<div class="icon maybe"></div>'

  # paid information
  text_paid = 'Not paid'
  div_paid = '<div class="icon no"></div>'
  if record.date_paid:
    text_paid = (
      'Paid on ' + record.date_paid.strftime(_PRETTY_TIME)
      # + ' (' + record.checkout_key +')' # todo linkify this
    )
    div_paid = '<div class="icon yes"></div>'
    if record.SPMUser_buyer:
      if record.SPMUser_buyer.name:
        text_paid += ' by ' + record.SPMUser_buyer.name
      elif record.SPMUser_buyer.email:
        text_paid += ' by ' + record.SPMUser_buyer.email
  else:
    if record.spm_name:
      pass # use default values from above
    else:
      # in this case we don't have a payment date and we don't have a spm_name
      # record indicating this was created by us.  This should never happen.
      logging.critical('Impossible situation.  Wtf.  Key=' + str(record.key()) + 
        ' Description=' + record.description)
      pass

  text_desc = 'Description unknown'
  if record.description:
    text_desc = record.description

  text_amount = '0.00'
  if record.amount:
    text_amount = '%0.2f' % float(record.amount)

  text_currency = record.currency
  if not text_currency:
    text_currency = 'ERROR'
  elif text_currency == 'USD':
    text_currency = '$'

  text_paynow = ''
  if record.checkout_payurl and not record.date_paid:
    text_paynow = '<a href="' + record.checkout_payurl + '">Pay now</a>'

  text_transaction = ''
  if record.spm_transaction:
    text_transaction = str(record.spm_transaction)

  if c14n_url and linkify:
    div_linestyle = '<div class="linehover" onclick="location.href=\'' + c14n_url + '\'">'
  else:
    div_linestyle = '\t<div class="linenohover">' 

  outbuf.append('\t' + div_linestyle) 
  outbuf.append('\t\t<div class="horizontalbox">')

  outbuf.append('\t\t\t<div class="verticalbox innerbox col-amount">')
  outbuf.append('\t\t\t\t<div class="innerspacer"></div>')

  outbuf.append('\t\t\t\t<div class="innerbox amount">' +
                '<div class="currency">' + text_currency + '&nbsp;</div>' + text_amount + '</div>')
  outbuf.append('\t\t\t\t<div class="innerspacer"></div>')
  outbuf.append('\t\t\t</div>')

  outbuf.append('\t\t\t<div class="verticalbox innerbox col-desc">')
  outbuf.append('\t\t\t\t<div class="innerspacer"></div>')
  outbuf.append('\t\t\t\t<div class="innerbox infotext">' + text_desc + '</div>')
  outbuf.append('\t\t\t\t<div class="innerbox infotext">' + div_paid + text_paid + '</div>')
  outbuf.append('\t\t\t\t<div class="innerspacer"></div>')
  outbuf.append('\t\t\t</div>')

  if IsMobile(useragent):
    # split to second line for mobile
    outbuf.append('\t\t\t</div>')
    outbuf.append('\t\t\t<div class="horizontalbox">')

  outbuf.append('\t\t\t<div class="verticalbox innerbox col-face">')
  outbuf.append('\t\t\t\t<div class="innerspacer"></div>')
  outbuf.append('\t\t\t\t<div class="innerbox picture" style="background-image:url(\'' + url_seller_picture + '\');"></div>')
  outbuf.append('\t\t\t\t<div class="innerspacer"></div>')
  outbuf.append('\t\t\t</div>')

  outbuf.append('\t\t\t<div class="verticalbox innerbox col-annotation">')
  outbuf.append('\t\t\t\t<div class="innerspacer"></div>')
  outbuf.append('\t\t\t\t<div class="innerbox infotext">' + text_seller + '</div>')
  outbuf.append('\t\t\t\t<div class="innerbox secondary">' + text_email + '</div>')
  outbuf.append('\t\t\t\t<div class="innerspacer"></div>')
  outbuf.append('\t\t\t</div>')

  outbuf.append('\t\t\t<div class="verticalbox innerbox col-paidbutton">')
  outbuf.append('\t\t\t\t<div class="innerspacer"></div>')
  outbuf.append('\t\t\t\t<div class="innerbox infotext">' + text_paynow + '</div>')
  outbuf.append('\t\t\t\t<div class="innerspacer"></div>')
  outbuf.append('\t\t\t</div>')

#  outbuf.append('\t\t\t<div class="verticalbox innerbox col-status">')
#  outbuf.append('\t\t\t\t<div class="innerspacer"></div>')
#  outbuf.append('\t\t\t\t<div class="innerbox infotext">' + div_sent + text_sent + '</div>')
#  outbuf.append('\t\t\t\t<div class="innerspacer"></div>')
#  outbuf.append('\t\t\t</div>')

  outbuf.append('\t\t</div>') # lineitem
  outbuf.append('\t</div>') # linehover
  
  return outbuf



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


class AppPage_Admin(webapp.RequestHandler):

  def get(self):

    # login required
    um = spmuser.UserManager()
    spm_loggedin_user = um.GetSPMUserByLoggedInGoogleAccount()
    if not spm_loggedin_user:
      self.redirect('/')
      return

    query = self.request.query
    if not query:
      self.redirect('/')
      return

    print query

    sync_value = long(self.request.get('sync'))
    if not sync_value:
      sync_value = 180
    if sync_value:
      print 'Starting background task to sync ' + str(sync_value) + ' days.'
      # TODO: move this to a background cron job or user-facing button
      taskqueue.add(queue_name='syncqueue', url='/task/checkout', params={
        'user_key': spm_loggedin_user.key(),
        'sync_value': sync_value,
      })


class TaskPage_SyncCheckout(webapp.RequestHandler):
  """Runs sync checkout in the background."""

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


class AppPage_Default(webapp.RequestHandler):

  def __init__(self):
    self._TITLE = SPM

  def get(self):
    """Returns main page."""

    um = spmuser.UserManager()
    spm_loggedin_user = um.GetSPMUserByLoggedInGoogleAccount()

    outbuf = []
    outbuf.append(CreateHeader(self._TITLE, self.request.headers.get('user_agent')))
    if spm_loggedin_user:
      outbuf.append('<div class="simple">Logged in, so go to <a href="/everything">everything</a>.</div>')
    else:
      outbuf.append('<div class="simple">Not logged in.  You should <a href="/signin">sign in</a>.</div>')
    outbuf.append(CreateFooter())
    self.response.out.write('\n'.join(outbuf))


class AppPage_Send(webapp.RequestHandler):
  """Login required."""


  def ReserveNextSerialsTransaction(self, spm_name, number_to_reserve):
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

    # login required
    um = spmuser.UserManager()
    spm_loggedin_user = um.GetSPMUserByLoggedInGoogleAccount()
    if not spm_loggedin_user:
      self.redirect('/')
      return

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

    outbuf = []
    outbuf.append(CreateHeader(self._TITLE, self.request.headers.get('user_agent')))
    outbuf.append('<div class="simple">')

    outbuf.append(_PAGE_CONTENT % {
      'posturl': self.request.path,
    })

    outbuf.append('</div>')
    outbuf.append(CreateFooter())
    self.response.out.write('\n'.join(outbuf))
    
    return


  def post(self):
    """Takes a HTML form post and creates a new expense"""

    # TODO: convert to JS/JSON with client side validation logic too

    # login required
    um = spmuser.UserManager()
    spm_loggedin_user = um.GetSPMUserByLoggedInGoogleAccount()
    if not spm_loggedin_user:
      self.redirect('/')
      return

    # seller bit required
    if not spm_loggedin_user.checkout_verified:
      self.redirect('/')
      return

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
      self.ReserveNextSerialsTransaction, newcr_spm_name, 1
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
        description = newcr_description
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
  """Login required"""

  def __init__(self):
    self._TITLE = SPM + ' everything'


  def get(self):

    # login required
    um = spmuser.UserManager()
    spm_loggedin_user = um.GetSPMUserByLoggedInGoogleAccount()
    if not spm_loggedin_user:
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

    _OTHER_DIVIDER_LINE = '<div class="compact">For other things (invoices not sent with sopay.me)</div>'
    _RECORD_DIVIDER_LINE = '<div class="compact">For <strong>%(forpart)s</strong> (<em>%(serialpart)s</em>)</div>'

    # group the records into a dict of lists keyed off of url. to be considered
    # in a grouping, the record must have a c14n url and a valid date_sent set,
    # otherwise stick it into the 'other things' category cause it wasn't sent
    # using sopay.me
    sort_buckets = {}
    time_sort = []
    for record in records:
      key_url = BuildSPMURL(record.spm_name, record.spm_serial, relpath=True)  
      if not key_url:
        key_url = _OTHER_DIVIDER_LINE
      else:
        # use split url so we get the nice three-digit formatting for #
        split_url = key_url.split('/') # (''/'for'/'name'/'serial')
        key_url = _RECORD_DIVIDER_LINE % ({
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
      if not url == _OTHER_DIVIDER_LINE:
        for record in sort_buckets[url]:
          if record.date_latest > date_max:
            date_max = record.date_latest
      list_to_sort.append((date_max, url))
    list_to_sort.sort(reverse = True)

    ##### start rendering page #####

    outbuf = []
    outbuf.append(CreateHeader(self._TITLE, self.request.headers.get('user_agent')))
    outbuf.append(_PAGE_SIMPLEDIV % {
      'message': (
        'Payment updates from Google Checkout may take up to an hour to appear. '
        '<a href="/a?sync=180">Refresh the last 180 days now.</a>'
        # TODO: remove this message when sync gets moved to cron
      )
    })

    # render the records
    for date, url_key in list_to_sort:
      outbuf.append(url_key)
      for record in sort_buckets[url_key]:
        hoverline = CreateHoverLine(record, linkify=True, useragent=self.request.headers.get('user_agent'))
        for line in hoverline:
          outbuf.append(line)

    # finish
    outbuf.append(CreateFooter())
    self.response.out.write('\n'.join(outbuf))


class AppPage_StaticPaylink(webapp.RequestHandler):
  """Accessible without login."""

  def get(self):
    """TODO"""

    um = spmuser.UserManager()
    spm_loggedin_user = um.GetSPMUserByLoggedInGoogleAccount()

    # TODO: acl'ed payments

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

    ##### start rendering page #####

    records_shown = False

    outbuf = []
    outbuf.append(CreateHeader(self._TITLE, self.request.headers.get('user_agent')))
    outbuf.append(_PAGE_SIMPLEDIV % {
      'message': 'Payment updates from Google Checkout may take up to an hour to appear.'
    })

    # query this as an iterable instead of fetch so we get them all
    records = db.GqlQuery(
      'SELECT * FROM PurchaseRecord '
      'WHERE spm_name = :1 AND spm_serial = :2',
      parsed_url['name'], parsed_url['serial']
    )
    for record in records:
      records_shown = True
      # TODO lookup seller as well
      hoverline = CreateHoverLine(record, linkify=False, useragent=self.request.headers.get('user_agent'))
      for line in hoverline:
        outbuf.append(line)

    outbuf.append(CreateFooter())

    # for now, alwasys show the checkout button
    #if records[0].checkout_payurl:
    #  outbuf.append(_CHECKOUT_BUTTON_HTML % {'button_url': records[0].checkout_payurl})
    #outbuf.append(CreateFooter())

    # if there aren't any records, there's nothing to show
    if not records_shown:
      self.redirect('/')
      return
    else:
      self.response.out.write('\n'.join(outbuf))


################################################################################


application = webapp.WSGIApplication([
  # Background task queues
  ('/task/checkout', TaskPage_SyncCheckout),
  # User-facing functional pages
  #('/connections', AppPage_Connections),
  ('/a', AppPage_Admin),
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