import logging          # common include for all files
from spmutil import *   # common include for all files

import time   # for setting timezone in main()
import os     # for setting timezone in main()

from google.appengine.ext import db
from google.appengine.api import taskqueue # enqueuing new sync requests
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

from datetime import datetime, timedelta
import pprint # for printing admin pages (ascii)
import spmcheckout
import spmuser


################################################################################


class AppPage_Admin(webapp.RequestHandler):


  def __init__(self):
    self._TITLE = 'admin'


  def get(self):
    """Admin-only stats page.  (Restricted in app.yaml)"""

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser(sudo_email = self.request.get('sudo'))

    if not spm_loggedin_user:
      self.redirect('/')
      return

    ##### setup #####

    pp = pprint.PrettyPrinter()
    outbuf = ['<body><pre>']

    ##### purchase stats #####

    purchases = db.GqlQuery(
      'SELECT * FROM PurchaseRecord'
    )

    num_spm = 0
    num_not_spm = 0
    num_paid = 0
    num_not_paid = 0
    dollaz = 0
    othaz = 0
    dollaz_not_paid = 0
    othaz_not_paid = 0
    for record in purchases:
      if record.date_sent:
        num_spm += 1
        if record.date_paid:
          num_paid += 1        
          if record.amount:
            if record.currency:
              if record.currency == 'USD':
                dollaz += float(record.amount)
              else:
                othaz += float(record.amount)        
        else:
          num_not_paid += 1
          if record.amount:
            if record.currency:
              if record.currency == 'USD':
                dollaz_not_paid += float(record.amount)
              else:
                othaz_not_paid += float(record.amount)  
      else:
        num_not_spm += 1

    # basic calculations
    percent_paid = (float(num_paid) / float(num_paid + num_not_paid)) * 100
    percent_not_paid = 100 - percent_paid
    average_paid = dollaz / num_paid

    # output
    outbuf.append('=== PURCHASES ===')
    outbuf.append('SPMs:                 ' + str(num_spm))
    outbuf.append('')
    outbuf.append('Paid:                 ' + str(num_paid) + ' (' + str(int(percent_paid)) + '%)')
    outbuf.append('Total $:              ' + str(dollaz))
    outbuf.append('Average SPM:          ' + str(average_paid))
    outbuf.append('')
    outbuf.append('Unpaid:               ' + str(num_not_paid) + ' (' + str(int(percent_not_paid)) + '%)')
    outbuf.append('Total unpaid $:       ' + str(dollaz_not_paid))
    outbuf.append('')
    outbuf.append('Total non-usd:        ' + str(othaz))
    outbuf.append('Total unpaid non-usd: ' + str(othaz_not_paid))
    outbuf.append('')
    outbuf.append('Non-SPM checkouts:    ' + str(num_not_spm))
    outbuf.append('\n\n')

    ##### namespace stats #####

    counts = db.GqlQuery(
      'SELECT * FROM CountStore ORDER BY url_count DESC'
    )

    cum_count = 0
    pre_outbuf = []
    for record in counts:
      cum_count += record.url_count
      pre_outbuf.append(str(record.url_count) + '\t' + str(record.key().parent().name()))

    outbuf.append('=== COUNTSTORE ===')
    outbuf.append('Unique names:         ' + str(counts.count()))
    outbuf.append('Unique names+serials: ' + str(cum_count))
    outbuf.append('')
    for line in pre_outbuf:
      outbuf.append(line)
    outbuf.append('\n\n')

    ##### user stats #####

    senders = db.GqlQuery(
      'SELECT * FROM SPMUser WHERE checkout_merchant_id != NULL'
    )

    outbuf.append('=== SENDERS ===')
    outbuf.append('Total unique emails: ' + str(senders.count()))
    outbuf.append('')
    for record in senders:
      output_text = ''
      if record.name:
        output_text += record.name + '\t'
      if record.email:
        output_text += record.email + '\t'
        output_text += '<a href="/debug?sudo=' + record.email + '">More</a>\t'
      outbuf.append(output_text)
    outbuf.append('\n\n')

    ##### user stats #####

    not_senders = db.GqlQuery(
      'SELECT * FROM SPMUser WHERE checkout_merchant_id = NULL'
    )

    outbuf.append('=== NOT SENDERS ===')
    outbuf.append('Total unique emails: ' + str(not_senders.count()) + '\n')
    for record in not_senders:
      output_text = ''
      if record.name:
        output_text += record.name + '\t'
      if record.email:
        output_text += record.email + '\t'
        output_text += '<a href="/debug?sudo=' + record.email + '">More</a>\t'
      outbuf.append(output_text)
    outbuf.append('\n\n')

    ##### done #####

    outbuf.append('</pre></body>')
    self.response.out.write('\n'.join(outbuf))


class AppPage_Debug(webapp.RequestHandler):


  def __init__(self):
    self._TITLE = 'debug'


  def get(self):
    """Publicly visible debug page.  Make sure requests here are limited to current user."""

    ##### identity #####

    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser(sudo_email = self.request.get('sudo'))

    if not spm_loggedin_user:
      self.redirect('/')
      return

    ##### always print #####

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
    outbuf.append('\n===INFO===\n')

    ##### functional things #####

    if spm_loggedin_user.checkout_verified:

      if self.request.path == '/debug/force': 
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
  
      elif self.request.path == '/debug/dump':
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


application = webapp.WSGIApplication([
  # User-facing
  ('/admin.*', AppPage_Admin),
  ('/debug.*', AppPage_Debug),
],debug=True)


def main():
  os.environ['TZ'] = 'US/Pacific'
  time.tzset()
  logging.getLogger().setLevel(logging.DEBUG)
  run_wsgi_app(application)


if __name__ == "__main__":
  main()