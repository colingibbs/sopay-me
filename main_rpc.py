# TODO: these imports are before the main_user, main_rpc, main_tasks split.  they all
# may or may not be needed, but I haven't bothered to check yet - zpm

import calendar
from datetime import datetime, timedelta
import time
import logging # DEBUG, INFO, WARNING, ERROR, CRITICAL
import os # for setting timezone
import re # for matching email addresses

from google.appengine.ext import db
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


class RPCMethods:
	
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
	
  def Submit(self, args):	
 
    #need the user's name for the db lookup
  	#using a random parameter for GetSPMUser().  hopefully won't break anything
    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser('blah')
   
    """expects to get these arguments:
    title, details, {emails}, {amounts}
    """
    url = args['title'] 
    #discovered that Zach called it URL (need to make consistent for better readability)
    
    details = args['details']
    temp_emails = args['emails']
    temp_amounts = args['amounts']
    
    #working around some Python typing weirdness
    if not isinstance(temp_emails, list):
      emails = [temp_emails]
    else:
      emails = temp_emails
    if not isinstance(temp_amounts, list):
      amounts = [temp_amounts]
    else:
      amounts = temp_amounts
    
    logging.debug('got submit order request from Android')
    logging.debug('Title: ' + url)
    logging.debug('Details: ' + details)
    for e in emails:
      logging.debug('Emails: ' + e)
    for a in amounts:
      logging.debug('Amounts: ' + a)  
    
    ##### form content validation #####

    form_amount_email_pairs = []
    for a, e in zip(amounts, emails):
      if a and e:
        form_amount_email_pairs.append((float(a), e.strip()))

    # url must be a-z, 0-9... no spaces or characters
    if not url.isalnum():
      logging.debug('FormValidator: URL failed.')
      self.error(500)
      return
      # TODO: user-facing notification in this case
    else:
      newcr_spm_name = str(url).lower()

    # simple validation, doesn't catch everything but works for the 99% use case
    _EMAIL_REGEX = '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,4}$'

    # needs to be numbers or decimals
    for form_amount, form_email in form_amount_email_pairs:
      if not form_amount:
        logging.debug('FormValidator: Amount failed')
        self.error(500)
        return
      if not form_email:
        logging.debug('FormValidator: Email address empty')
        self.error(500)
        return
      else:
        if not re.search(_EMAIL_REGEX, form_email):
          logging.debug('FormValidator: Email address failed regex: ' + form_email)
          self.error(500)
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
      new_pr.description = details
      new_pr.date_sent = datetime.utcnow()
      new_pr.date_latest = new_pr.date_sent
      new_pr.sent_to_email = email
      new_pr.SPMUser_sentto = user_manager.GetSPMUserByEmail(email)

      spmid = BuildSPMID(
        name = new_pr.spm_name,
        serial = new_pr.spm_serial,
        transaction = new_pr.spm_transaction,
      )
  
      checkout = spmcheckout.CheckoutSellerIntegration(spm_loggedin_user)
      checkout_payurl = checkout.GetPaymentUrl(
        spm_full_id = spmid,
        description = new_pr.spm_name + ' (' + new_pr.description + ')',
        amount = new_pr.amount,
        currency = new_pr.currency,
      )
      new_pr.checkout_payurl = checkout_payurl

      if not checkout_payurl:
        logging.critical('New invoice: GetPaymentUrl failed')
        self.error(500)
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
      spm_to_user = user_manager.GetSPMUserByEmail(email)
      emailer.SendEmail(
        to_name = spm_to_user.name,
        to_email = email,
        spm_for = newcr_spm_name,
        spm_url = BuildSPMURL(
          name = new_pr.spm_name,
          serial = new_pr.spm_serial,
        ),
        pay_url = checkout_payurl,
        description = details,
        amount = new_pr.amount, 
      )

      # commit record - do this last in case anything above fails
      new_pr.put()

      # iterate item count for next thing
      item_count += 1
    
    return True

  def GetAll(self, *args):
  
  	#need the user's name for the db lookup
  	#using a random parameter for GetSPMUser().  hopefully won't break anything
    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser('blah')
    
    
    ##### lifted from another method - use this to get the records #####

    # query as an iterable instead of fetch so we get all the records
    records = db.GqlQuery(
      'SELECT * FROM PurchaseRecord '
      'WHERE SPMUser_seller = :1 '
      'ORDER BY date_latest DESC ',
      spm_loggedin_user
    )
    
    _OTHER_STRING = 'For other things (invoices not sent with sopay.me)'
    _RECORD_STRING = 'For %(forpart)s (%(serialpart)s)'
 
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
        
      #don't add the entire record.  just add the stuff we need for the Android app
      #TODO: rewrite this once we know what we want to show in the app
      sort_buckets[key_url].append(record.checkout_buyer_name)
      sort_buckets[key_url].append(record.amount)
      sort_buckets[key_url].append(record.description)
      
    return sort_buckets


################################################################################


application = webapp.WSGIApplication([
  # API
  ('/rpc', AppPage_RPC),
],debug=True)


def main():
  os.environ['TZ'] = 'US/Pacific'
  time.tzset()
  logging.getLogger().setLevel(logging.DEBUG)
  run_wsgi_app(application)


if __name__ == "__main__":
  main()