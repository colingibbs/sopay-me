import logging
from spmutil import *

from google.appengine.ext import db # run transactions
import spmdb # for creating new records, incrementing countstore
import spmcheckout # for creating checkout urls when creating new records
import spmuser # for sending emails
from datetime import datetime # recording transaction time
import re # for matching email addresses
import spmemail # for sending emails



################################################################################


class NewBill():
  """Business logic and validation logic that creates a new bill."""


  def __init__(self, name, description, amount_email_pairs):
    """Sets variables."""

    self.url_name = name
    self.description = description
    self.amount_email_pairs = amount_email_pairs
    
    self.data_validated = False


  def __ReserveNextSerial(self, name_to_reserve, number_to_reserve = 1):
    """Runs the transaction to reserve a serial number."""

    return db.run_in_transaction(
      self.__ReserveNextSerialsTransaction, name_to_reserve, number_to_reserve
    )


  def __ReserveNextSerialsTransaction(self, name_to_reserve, number_to_reserve):
    """Reserves the next serial numbers."""

    count_record = None
    count_records = db.GqlQuery(
      'SELECT * FROM CountStore WHERE ANCESTOR IS :1',
      db.Key.from_path('CountURL', name_to_reserve)
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
        parent = db.Key.from_path('CountURL', name_to_reserve),
        url_count = number_to_reserve
      )
      new_record.put()
      return 0
      
      
  def DataValidated(self):
    """Validates input data, and if valid, reserves the serial."""

    # url must be a-z, 0-9... no spaces or characters
    if not self.url_name.isalnum():
      return False
    else:
      self.url_name = str(self.url_name).lower()

    # if no description is provided, just pull in url_name
    if not self.description:
      self.description = self.url_name
    else:
      self.description = str(self.description)

    # email validation, doesn't catch everything but works for the 99% use case
    _EMAIL_REGEX = '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,4}$'

    # needs to be numbers or decimals
    for amount, email in self.amount_email_pairs:
      if not amount:
        return False
      if not email:
        return False
      else:
        if not re.search(_EMAIL_REGEX, email):
          logging.debug('spmnewbill: Email address failed regex: ' + email)
          return False
    
    self.data_validated = True
    return True


  def CommitAndSend(self, spm_loggedin_user):
    """Commits changes to db.  Returns true if successful."""

    # ensure that DataValidated has been run successfully
    if not self.data_validated:
      return False

    # set url_serial
    self.url_serial = self.__ReserveNextSerial(self.url_name)

    # for sending emails
    user_manager = spmuser.UserManager()

    item_count = 0
    for amount, email in self.amount_email_pairs:

      new_pr = spmdb.PurchaseRecord(
        parent = MakeAncestorFromSPMUser(spm_loggedin_user),
        SPMUser_seller = spm_loggedin_user.key()
      )
      new_pr.spm_name = self.url_name
      new_pr.spm_serial = self.url_serial
      new_pr.spm_transaction = item_count
      new_pr.amount = '%0.2f' % float(amount)
      new_pr.currency = 'USD'
      new_pr.description = self.description
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
        # if you change any of the above fields, make sure to change the
        # checkout sync code appropriately as well, as it checks all four
      )

      if not checkout_payurl:
        logging.critical('spmnewbill: GetPaymentUrl failed')
        return False
        # TODO: retry, better error handling, and user-facing notification in this case
      else:
        new_pr.checkout_payurl = checkout_payurl

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
        spm_for = new_pr.spm_name,
        spm_url = BuildSPMURL(
          name = new_pr.spm_name,
          serial = new_pr.spm_serial,
        ),
        pay_url = checkout_payurl,
        description = self.description,
        amount = new_pr.amount, 
      )

      # commit record - do this last in case anything above fails
      new_pr.put()

      # iterate item count for next thing
      item_count += 1
    
    # return success
    return True
