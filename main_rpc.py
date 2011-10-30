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

from django.utils import simplejson # for encoding responses

# local imports
import spmdb
import spmemail
import spmcheckout
import spmnewbill   # used in send now class
import spmuser
from spmutil import *


################################################################################


class RPCMethods:

	
  def Submit(self, args):	
 
    # need the user's name for the db lookup
    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser() # no sudo from app
   
    """expects to get these arguments:
    title, details, {emails}, {amounts}
    """
    form_name = args['title'] 
    # discovered that Zach called it URL (need to make consistent for better readability)
    
    form_description = args['details']
    temp_emails = args['emails']
    temp_amounts = args['amounts']
    
    # working around some Python typing weirdness
    if not isinstance(temp_emails, list):
      emails = [temp_emails]
    else:
      emails = temp_emails
    if not isinstance(temp_amounts, list):
      amounts = [temp_amounts]
    else:
      amounts = temp_amounts
    
    logging.debug('got submit order request from Android')
    logging.debug('Title: ' + form_name)
    logging.debug('Details: ' + form_details)
    for e in emails:
      logging.debug('Emails: ' + e)
    for a in amounts:
      logging.debug('Amounts: ' + a)  

    form_amount_email_pairs = []
    for amount, email in zip(amounts, emails):
      if amount and email:
        form_amount_email_pairs.append((float(amount), email.strip()))

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


class AppPage_RPC(webapp.RequestHandler):
  """Checkout account required."""

  def __init__(self):
    webapp.RequestHandler.__init__(self)
    self.methods = RPCMethods()

  def get(self):

    ##### identity #####
    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser(sudo_email = self.request.get('sudo'))

    if not spm_loggedin_user.checkout_verified:
      self.response.out.write(simplejson.dumps('Your account needs to be verified'))
      return

    ##### handle RPC requests #####
    func = None
    
    action = self.request.get('action')
    if action:
      if action[0] == '_':
        self.error(403)
    	return
      else:
        func = getattr(self.methods, action, None)
    		
    if not func:
      self.error(404) #action not found
      return
    	
    args = ()
    while True:
      key = 'arg%d' % len(args)
      val = self.request.get(key)
      if val:
        args += (simplejson.loads(val),)
      else:
        break
    result = func(*args)
    self.response.out.write(simplejson.dumps(result))
    
  def post(self):
      
    ##### identity #####
    user_manager = spmuser.UserManager()
    spm_loggedin_user = user_manager.GetSPMUser(sudo_email = self.request.get('sudo'))

    if not spm_loggedin_user.checkout_verified:
      self.response.out.write(simplejson.dumps('Your account needs to be verified'))
      return
    
    
    args = simplejson.loads(self.request.body)
    func = args['action']
    if func[0] == '_':
      self.error(403) # access denied
      return

    func = getattr(self.methods, func, None)
    if not func:
      self.error(404) # file not found
      return

    result = func(args)
    self.response.out.write(simplejson.dumps(result))


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