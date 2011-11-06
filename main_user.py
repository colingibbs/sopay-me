import logging          # common include for all files
from spmutil import *   # common include for all files

import time   # for setting timezone in main()
import os     # for setting timezone in main()

from google.appengine.ext import db
from google.appengine.api import users # for login/logout urls
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

import cgi # used for form encoding in /now
from datetime import datetime, timedelta
import spmnewbill   # used in send now class
import spmcheckout
import spmbuilder # page building class
import spmuser


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


class AppPage_Error(webapp.RequestHandler):

  def __init__(self):
    self._TITLE = SPM

  def get(self):
    """Returns error page."""

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser(sudo_email = self.request.get('sudo'))

    ##### preprocessing before rendering page #####

    page = spmbuilder.NewPage(
      title = self._TITLE,
      user = spm_loggedin_user,
      useragent = self.request.headers.get('user_agent'),
      uideb = self.request.get('uideb'),
      nav_code = None,
    )

    page.AppendNavbar()
    page.AppendLine('<br/><br/>Well, that wasn\'t supposed to happen.')

    self.response.out.write(page.Render())


class AppPage_Default(webapp.RequestHandler):

  def __init__(self):
    self._TITLE = SPM

  def get(self):
    """Returns main page."""

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser(sudo_email = self.request.get('sudo'))

    ##### preprocessing before rendering page #####

    # show all records explicitly sent to this user

    # query as an iterable instead of fetch so we get all the records
    # TODO: implement paging    
    if spm_loggedin_user:
      records = db.GqlQuery(
        'SELECT * FROM PurchaseRecord '
        'WHERE SPMUser_sentto = :1 '
        'ORDER BY date_latest DESC ',
        spm_loggedin_user
      )
    else:
      records = []

    ##### render page #####

    page = spmbuilder.NewPage(
      title = self._TITLE,
      user = spm_loggedin_user,
      useragent = self.request.headers.get('user_agent'),
      uideb = self.request.get('uideb'),
      nav_code = "NAV_YOUPAY",
    )

    if not spm_loggedin_user:
      # welcome note
      page.AppendLine('<br/><br/>The easy way to send payments to friends.')
  
    else:
      page.AppendNavbar()
      # welcome note
      if not spm_loggedin_user.checkout_verified:
        page.AppendLine('Your sopay.me\'s are listed below. Want to send new sopay.me\'s? Well, you can\'t right now, because you don\'t have a Google Checkout seller account set up. Email Zach if you have one and want to participate in the sopay.me beta.')
        page.AppendLineShaded('')

      # display your outstanding purchases, don't bother for things not sent with
      # sopay me (no need to do advanced keying or grouping at the moment
      for record in records:
        if record.spm_name:
          leader_line = BuildSPMURL(record.spm_name, record.spm_serial, relpath=True)  
          if leader_line:
            # use split url so we get the nice three-digit formatting for #
            split_url = leader_line.split('/') # (''/'for'/'name'/'serial')
            split_name = record.SPMUser_seller.name.split(' ') # TODO: probably some verification here
            page.AppendLine('Pay ' + split_name[0] + ' for <strong>' + split_url[2] + '</strong> ...')
          page.AppendHoverRecord(record = record, linkify = True, show_seller_instead = True)
          page.AppendLineShaded('')

    self.response.out.write(page.Render())


class AppPage_PaymentHistory(webapp.RequestHandler):
  """Checkout account required."""

  def __init__(self):
    self._TITLE = SPM


  def get(self):

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser(sudo_email = self.request.get('sudo'))

    if not spm_loggedin_user:
      self.redirect('/')
      return
    elif not spm_loggedin_user.checkout_verified:
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

    _OTHER_STRING = 'For other things (invoices not sent with sopay.me) ...'
    _RECORD_STRING = 'For <strong>%(forpart)s</strong> ...'

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
      try:
        sort_buckets[key_url]
      except KeyError:
        sort_buckets[key_url] = []
      sort_buckets[key_url].append(record)


    # sort by the most recent update in each of the buckets, but
    # always sort 'other' last (these are the things not sent with spm)
    list_to_sort = []
    for url in sort_buckets.keys():
      date_max = datetime(1985,9,17) # way in the past... like when zach was born
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
      nav_code = 'NAV_THEYPAY',
    )

    page.AppendNavbar()

    for date, url_key in list_to_sort:
      if not url_key == _OTHER_STRING:
        split_url = url_key.split('/') # (''/'for'/'name'/'serial')
        display_url = _RECORD_STRING % ({
          'forpart': split_url[2], 
          #'serialpart': split_url[3],
        })
        page.AppendLine(display_url)
      else:
        page.AppendLine(_OTHER_STRING)
      for record in sort_buckets[url_key]:
        if spm_loggedin_user:
          page.AppendHoverRecord(record = record, linkify = True)
        else:
          page.AppendHoverRecord(record = record, linkify = True)
      page.AppendLineShaded('')

    self.response.out.write(page.Render())


class AppPage_StaticPaylink(webapp.RequestHandler):
  """Accessible without login."""

  def get(self):
    """TODO"""

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser(sudo_email = self.request.get('sudo'))

    # TODO: acl'ed payments
    # if not spm_loggedin_user.checkout_verified:
    #  self.redirect('/')
    #  return

    ##### preprocessing before rendering page #####

    # validate url
    parsed_url = ParseSPMURL(self.request.path, relpath=True)
    if not parsed_url:
      self.redirect("/")
      return

    # if digit is too short rewrite and redirect to 3char+
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
      nav_code = None,
    )

    top_text = 'Note: Payment updates from Checkout may take up to an hour to appear.'
    if not spm_loggedin_user:
      top_text += ' Sign in to see full names and emails.'

    page.AppendNavbar()
    page.AppendLine(top_text)
    page.AppendLineShaded('')

    is_first = True
    for record in records:
      if is_first:
        page.AppendIdentity(record = record, show_seller_instead = True)
        page.AppendLineShaded('')
        is_first = False
      records_shown = True
      if spm_loggedin_user:
        page.AppendHoverRecord(record = record, linkify = False)
      else:
        page.AppendHoverRecord(record = record, linkify = False)

    # if there aren't any records, there's nothing to show
    if not records_shown:
      self.redirect('/')
      return
    else:
      self.response.out.write(page.Render())


class AppPage_Send(webapp.RequestHandler):
  """Checkout account required."""


  def __init__(self):
    self._TITLE = SPM + ' now'


  def get(self):

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser(sudo_email = self.request.get('sudo'))

    if not spm_loggedin_user:
      self.redirect('/')
      return
    elif not spm_loggedin_user.checkout_verified:
      self.redirect('/')
      return

    ### render page ###

    _HACKY_FORM_CONTENT = \
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
      nav_code = "NAV_SENDNOW",
    )

    page.AppendNavbar()
    page.AppendLine('There\'s like, uh, no input validation on this page. You can and will break it if you\'re dumb.')

    page.AppendLine(_HACKY_FORM_CONTENT % {'posturl': self.request.path})
    self.response.out.write(page.Render())


  def post(self):
    """Takes a HTML form post and creates a new expense"""

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser(sudo_email = self.request.get('sudo'))

    if not spm_loggedin_user:
      self.redirect('/')
      return
    elif not spm_loggedin_user.checkout_verified:
      self.redirect('/')
      return

    ##### parse form #####
    # TODO: convert to JS/JSON with client side validation logic too

    form_name = cgi.escape(self.request.get('url'))
    # form_serial is automatically assigned
    form_description = cgi.escape(self.request.get('description'))

    form_amount_email_pairs = []
    for i in range(0,7):
      cur_amount = cgi.escape(self.request.get('amount' + str(i)))
      cur_email = cgi.escape(self.request.get('email' + str(i)))
      if cur_amount and cur_email:
        form_amount_email_pairs.append((float(cur_amount), cur_email.strip()))

    ##### create new bill #####

    new_bill = spmnewbill.NewBill(
      name = form_name,
      description = form_description,
      amount_email_pairs = form_amount_email_pairs,
    )
    if new_bill.DataValidated():
      if new_bill.CommitAndSend(spm_loggedin_user = spm_loggedin_user):
        # note that there's a datastore delay so we can't redirect immediately to
        # the pay page, so instead redirect to the seller view page
        self.redirect('/everything')  
      else:
        # commit and send failed
        self.redirect('/error')
    else:
      # validation failed
      self.redirect('/error')


################################################################################


application = webapp.WSGIApplication([
  # User-facing
  ('/error', AppPage_Error),
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