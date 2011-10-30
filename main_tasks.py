import logging          # common include for all files
from spmutil import *   # common include for all files

import time   # for setting timezone in main()
import os     # for setting timezone in main()

from datetime import datetime, timedelta

from google.appengine.ext import db
from google.appengine.api import taskqueue # for checkout sync quests
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

import spmdb # for writing daily logs
import spmcheckout


################################################################################


class TaskPage_SyncCheckout(webapp.RequestHandler):
  """Runs sync checkout in the background.
  Admin only access (app.yaml)"""

  def post(self):

    user_key = self.request.get('user_key')
    spm_user_to_run = db.get(user_key)
    sync_value = long(self.request.get('sync_value'))
    
    logging.debug('Task SyncCheckout starting.  User_key [' + user_key + ']' + 
                  ' sync_value [' + str(sync_value) + ']')

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

    logging.debug('Task SyncCheckout complete.  User_key [' + user_key + ']')


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


class TaskPage_DailyLogsCron(webapp.RequestHandler):
  """Runs daily metrics script.
  Admin only access (app.yaml)"""

  def get(self):

    ##### setup #####

    # even though this might not run _exactly_ at 2:00 UTC, key off of that date
    # so that there is an easy field to see for logs analysis.  also record the
    # run_on time for error checking, etc.

    right_now = datetime.utcnow()
    # if you change below, change cron time
    run_for = datetime(right_now.year, right_now.month, right_now.day, 2, 0, 0, 0, None) 
    todays_record = self.__GetTodaysLogsRecord(run_for)
    todays_record.date_actually_run_on = right_now

    # time delays
    days_ago_1 = right_now + timedelta(days = -1)
    days_ago_7 = right_now + timedelta(days = -7)
    days_ago_30 = right_now + timedelta(days = -30)

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
    
    today_active = 0
    today_new_spm = 0
    today_new_dollaz = 0
    today_num_paid = 0
    today_dollaz_paid = 0

    for record in purchases:
      # sent from spm
      if record.date_sent:
        num_spm += 1
        # paid through spm
        if record.date_paid:
          num_paid += 1     
          if record.amount:
            if record.currency:
              if record.currency == 'USD':
                dollaz += float(record.amount)
                # HAPPENED TODAY
                if record.date_paid > days_ago_1:
                  today_num_paid += 1
                  today_dollaz_paid += float(record.amount)
              else:
                othaz += float(record.amount)
        # not paid through spm
        else:
          num_not_paid += 1
          if record.amount and record.currency:
            if record.currency == 'USD':
              dollaz_not_paid += float(record.amount)
            else:
              othaz_not_paid += float(record.amount)
        # HAPPENED TODAY
        if record.date_sent > days_ago_1:
          today_new_spm += 1
          if record.amount and record.currency:
            if record.currency == 'USD':
              today_new_dollaz += float(record.amount)
      # not sent from spm 
      else:
        num_not_spm += 1
      if record.date_latest:
        if record.date_latest > days_ago_1:
          today_active += 1

    # output
    todays_record.num_spm = num_spm
    todays_record.num_spm_paid = num_paid
    todays_record.num_spm_not_paid = num_not_paid
    todays_record.paid_currency_dollars = float(dollaz)
    todays_record.paid_currency_other = float(othaz)
    todays_record.not_paid_currency_dollars = float(dollaz_not_paid)
    todays_record.not_paid_currency_other = float(othaz_not_paid)

    todays_record.num_not_spm = num_not_spm

    todays_record.today_records_active = today_active
    todays_record.today_new_num_spm_sent = today_new_spm
    todays_record.today_new_currency_dollars_sent = float(today_new_dollaz)
    todays_record.today_new_num_spm_paid = today_num_paid
    todays_record.today_new_currency_dollars_paid = float(today_dollaz_paid)
    

    ##### namespace stats #####

    counts = db.GqlQuery(
      'SELECT * FROM CountStore'
    )

    count = 0
    cum_count = 0
    for record in counts:
      count += 1
      cum_count += record.url_count

    todays_record.namespace_names = count
    todays_record.namespace_name_serials = cum_count

    ##### user stats #####

    users = db.GqlQuery(
      'SELECT * FROM SPMUser'
    )

    user_count = 0
    user_1d = 0
    user_7d = 0
    user_30d = 0

    for user in users:
      user_count += 1
      if user.last_login:
        if user.last_login > days_ago_1:
          user_1d += 1
        if user.last_login > days_ago_7:
          user_7d += 1
        if user.last_login > days_ago_30:
          user_30d += 1

    todays_record.users = user_count
    todays_record.users_loggedin_1d = user_1d
    todays_record.users_loggedin_7d = user_7d
    todays_record.users_loggedin_30d = user_30d

    senders = db.GqlQuery(
      'SELECT * FROM SPMUser WHERE checkout_merchant_id != NULL'
    )

    todays_record.users_with_checkout = senders.count()

    not_senders = db.GqlQuery(
      'SELECT * FROM SPMUser WHERE checkout_merchant_id = NULL'
    )

    todays_record.users_without_selling_ability = not_senders.count()

    ##### done #####

    todays_record.put()


  def __GetTodaysLogsRecord(self, date):
    """Gets today's logs record based on date."""

    logs_record = None
    logslist = db.GqlQuery(
      'SELECT * FROM DailyLogs WHERE date_key = :1', date
    ).fetch(limit=2)

    if len(logslist) == 1:
      logs_record = logslist[0]
    elif len(logslist) == 0:
      logs_record = spmdb.DailyLogs(date_key = date)
    else:
      logging.critical('Query returned more than one DailyLogs with date [' + date + ']')

    return logs_record


################################################################################


application = webapp.WSGIApplication([
  # Background task queues
  ('/task/checkout', TaskPage_SyncCheckout),
  ('/task/synccron', TaskPage_SyncCron),
  ('/task/logscron', TaskPage_DailyLogsCron),
],debug=True)


def main():
  os.environ['TZ'] = 'US/Pacific'
  time.tzset()
  logging.getLogger().setLevel(logging.DEBUG)
  run_wsgi_app(application)


if __name__ == "__main__":
  main()