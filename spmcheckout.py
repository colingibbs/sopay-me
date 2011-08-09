"""All integration with Google checkout is in this file."""

import base64
from datetime import datetime
import logging # DEBUG, INFO, WARNING, ERROR, CRITICAL
import pprint # for testing/debugging only
import random # for testing/debugging only
import xml
from xml.dom.minidom import parseString

from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

import spmdb
import spmuser
from spmutil import *


################################################################################


# note that 2.6 can support %f to parse microseconds but GAE doesn't run it
_CHECKOUT_UTC_FORMATTER_IN = '%Y-%m-%dT%H:%M:%S'
_CHECKOUT_UTC_FORMATTER = '%Y-%m-%dT%H:%M:%S.00Z'

_CHECKOUT_NOTIFICATION_HISTORY_URL = 'https://checkout.google.com/api/checkout/v2/reports/Merchant/%(merchant_id)s'
_CHECKOUT_API_SANDBOX_URL = 'https://sandbox.google.com/checkout/api/checkout/v2/merchantCheckout/Merchant/%(merchant_id)s'
_CHECKOUT_API_URL = 'https://checkout.google.com/api/checkout/v2/merchantCheckout/Merchant/%(merchant_id)s'


################################################################################


class CheckoutSellerIntegration:

  def __init__(self, spm_seller_user):
    self.spm_seller_user = spm_seller_user

  def __ParseCheckoutTime(self, s):
      parts = s.split('.')
      return datetime.strptime(parts[0], _CHECKOUT_UTC_FORMATTER_IN)


  def __CheckoutRequestHeaders(self): 
    return {
      'Authorization': ('Basic ' + base64.b64encode(
        self.spm_seller_user.checkout_merchant_id + ':' +
        self.spm_seller_user.checkout_merchant_secret)
      ),
      'Content-Type': 'application/xml;charset=UTF-8',
      'Accept': 'application/xml;charset=UTF-8'
    }


  def __MakeDictFromSellerHistoryXMLResponse(self, this_node):
    """Recurses through XML DOM and returns a dict object."""

    child = this_node.firstChild
    if not child:
      return None
    elif child.nodeType == xml.dom.minidom.Node.TEXT_NODE:
      return child.nodeValue

    d={}

    child_number = 0
    while child is not None:
      child_number += 1
      if child.nodeType == xml.dom.minidom.Node.ELEMENT_NODE:
        # if node has serial number, it's repeated so key off of serial-number
        if child.hasAttribute('serial-number'):
          key = child.getAttribute('serial-number')
          d[key] = self.__MakeDictFromSellerHistoryXMLResponse(child)
          d[key]['sopay-me/google-type'] = child.tagName
        # otherwise just add node as normal
        else:
          key = child.tagName
          # items (and potentially other fields) are also repeated, give unique key
          if child.tagName in ['item']:
            key += str(child_number)
          d[key] = self.__MakeDictFromSellerHistoryXMLResponse(child)

        if child.hasAttribute('currency'):
          d[child.tagName + '-currency'] = child.getAttribute('currency')
 
      # NEXT!
      child = child.nextSibling

    return d


  def __XMLPreprocessing(self, node):
    remove_list = []
    for child in node.childNodes:
      if child.nodeType == xml.dom.Node.TEXT_NODE and not child.data.strip():
        remove_list.append(child)
      elif child.hasChildNodes():
        self.__XMLPreprocessing(child)
    for node in remove_list:
      node.parentNode.removeChild(node)
      node.unlink()


  def __ParseCheckoutSellerHistorySingleResponse(self, response):
    # todo add error parsing and xml schema validation
    doc = xml.dom.minidom.parseString(response)
    self.__XMLPreprocessing(doc.documentElement)
    return self.__MakeDictFromSellerHistoryXMLResponse(doc.documentElement)
    

  def __ParseCheckoutCartResponse(self, response):
    # todo add error parsing and xml schema validation
    doc = xml.dom.minidom.parseString(response)
    self.__XMLPreprocessing(doc.documentElement)
    text = None
    
    for child in doc.documentElement.childNodes: # <checkout-redirect>
      if child.tagName == 'redirect-url':
        text = child.firstChild.nodeValue
    return text


  def __ApplyTransaction(self, notify):
    """Only call as trasnaction"""

    # EXAMPLE NOTIFY INPUT (nested dicts)
    # look for 'sopay-me/type'
    # Whitelist notifications; all have 'timestamp' and 'google-order-number'
    # new-order-notification
    #   'order-total': '40.0 USD'
    #   'shopping-cart': {'items': {'item1': {'item-description': 'Awesomeness',
    #                                         'item-name': 'Payment request from Zachary P Maier',
    #                                         'merchant-item-id': None,
    #                                         'quantity': '1',
    #                                         'unit-price': '40.0 USD'}}},
    #   'buyer-billing-address': 'contact-name': 'Denis S Sosnovtsev'
    #   'buyer-id': '947622132556905'
    #   ... and lots of other stuff we could log but will ignore
    # charge-amount-notification:
    #   latest-charge-amount '15.0 USD'
    #   total-charge-amount '15.0 USD'
    # order-state-change-notification: 
    #   (not currently used)
    #   'new-financial-order-state': 'CHARGED' / 'CHARGING' / 'CHARGEABLE'
    #   'new-fulfillment-order-state': 'PROCESSING',
    #   'previous-financial-order-state': (same as new-financial-order-state)
    #   'previous-fulfillment-order-state': 'PROCESSING',
    # risk-information-notification:
    #   (not currently used)

    this_record = None

    ##### identify which record to update #####

    checkout_key = notify['google-order-number']

    # easiest update - checkout key already in system
    if not this_record:
      existing_records = db.GqlQuery(
        'SELECT * FROM PurchaseRecord WHERE ANCESTOR IS :1 AND checkout_key = :2',
        MakeAncestorFromSPMUser(self.spm_seller_user), checkout_key
      ).fetch(limit=2)
      if len(existing_records) == 1:
        #logging.debug('Found record with checkout key = ' + checkout_key)
        this_record = existing_records[0]
      elif len(existing_records) >= 2:
        logging.critical('More than one record returned with same checkout_key')
      #else:
      #  logging.debug('Could not find record with checkout key = ' + checkout_key)

    ##### extract all the data #####

    # switch extraction on notification type
    notification_primary = notify['sopay-me/google-type']
    if notification_primary == 'new-order-notification':
      
      # general information
      notification_timestamp = self.__ParseCheckoutTime(notify['timestamp'])
      # purchase information
      notification_amount = notify['order-total']
      notification_currency = notify['order-total-currency']
      # get buyer information
      notification_checkout_buyer_email = notify['buyer-billing-address']['email']
      notification_checkout_buyer_name = notify['buyer-billing-address']['contact-name']
      notification_checkout_buyer_id = notify['buyer-id']
      # get individual item information
      # TODO loop through all items and treat separately
      notification_description = notify['shopping-cart']['items']['item1']['item-description']
      try:
        notification_private_data = notify['shopping-cart']['items']['item1']['merchant-private-item-data']
      except KeyError:
        notification_private_data = None


      # TODO: # REMOVE THIS HACK # REMOVE THIS HACK # REMOVE THIS HACK
      # used for testing locally on zach's desktop
      todo_remove_test_override_date_sent = None
      if notification_primary == 'new-order-notification' and notification_private_data:
        if notification_private_data == 'sopay.me/for/TEST_20110720':
          notification_private_data = 'sopay.me/for/duptest/000/' + notification_amount[2]
          todo_remove_test_override_date_sent = datetime(2011, 1, 11, 1, 11)
          if notification_amount == '0.77':
            notification_checkout_buyer_email = 'zpm@google.com'
        elif notification_private_data == '340101':
          notification_private_data = 'sopay.me/for/test2/000/0'
          todo_remove_test_override_date_sent = datetime(2011, 2, 22, 2, 22)
        elif notification_private_data == 'sopay.me/for/TEST_20110720_439':
          notification_private_data = 'sopay.me/for/test3-nosend/000/0'
        elif notification_private_data == 'sopay.me/for/TEST_20110720_number2':
          notification_private_data = 'sopay.me/for/test4-nosend/000/0'
        elif notification_private_data == 'sopay.me/for/Q':
          notification_private_data = 'sopay.me/for/test5/000/0'
          todo_remove_test_override_date_sent = datetime(2011, 5, 5, 5, 5)
      # TODO: # REMOVE THIS HACK # REMOVE THIS HACK # REMOVE THIS HACK



      # output status for debugging
      #logging.debug('Running update for...')
      #if notification_private_data:
      #  logging.debug('     Private: ' + notification_private_data)
      #if notification_description:
      #  logging.debug('     Desc: ' + notification_description)

      # if there's not yet a record, try to find one using name/serial/transaction
      parsed_id = ParseSPMID(notification_private_data)
      if not this_record and parsed_id:
        logging.debug('Querying ' + parsed_id['c14n'])
        existing_records = db.GqlQuery(
          'SELECT * FROM PurchaseRecord ' +
          'WHERE ANCESTOR IS :1 AND spm_name = :2 AND spm_serial = :3 ' + 
          'AND spm_transaction = :4 AND checkout_key = NULL',
          MakeAncestorFromSPMUser(self.spm_seller_user),
          parsed_id['name'], parsed_id['serial'], parsed_id['transaction']
        ).fetch(limit=2)
        if len(existing_records) == 1:
          logging.debug('Matched spm_name/serial/transaction.  Notification:')
          logging.debug(notification_amount)
          logging.debug(notification_currency)
          logging.debug(notification_description)
          # match this record using our criteria
          logging.debug('Trying to update existing record:')
          logging.debug(existing_records[0].amount)
          logging.debug(existing_records[0].currency)
          logging.debug(existing_records[0].description)
          # check float() to catch enter 1.00 return 1.0
          if float(existing_records[0].amount) == float(notification_amount):
            if existing_records[0].currency == notification_currency:
              if existing_records[0].description == notification_description:
                this_record = existing_records[0]
                logging.debug('MATCH! Going to update this one.')
          if not this_record:
            # this case means that the name/serial/transaction matched, but one
            # of the other details didn't match.  So we just create a new record
            logging.debug('Not a match.  Creating new.')
        elif len(existing_records) >= 2:
          logging.critical('More than one record returned with same spm name/serial/transaction')
        else:
          logging.critical('Received new order without name/serial/transaction in system')

      # already checked to see if this checkout order was in the system or the
      # this_recordivate data spm name/serial were in the system... and if neither of 
      # them were, just create the new order record
      if not this_record:
        this_record = spmdb.PurchaseRecord(
          parent = MakeAncestorFromSPMUser(self.spm_seller_user),
          SPMUser_seller = self.spm_seller_user.key()
        )

      # .... by this point this_record definitely exists, so let the updating begin ....



      # TODO: # REMOVE THIS HACK # REMOVE THIS HACK # REMOVE THIS HACK
      # used for testing locally on zach's desktop
      if todo_remove_test_override_date_sent:
        if not this_record.date_sent:
          this_record.date_sent = todo_remove_test_override_date_sent
        elif todo_remove_test_override_date_sent > this_record.date_sent:
          this_record.date_sent = todo_remove_test_override_date_sent
        if not this_record.date_latest:
          this_record.date_latest = todo_remove_test_override_date_sent      
        elif todo_remove_test_override_date_sent > this_record.date_latest:
          this_record.date_latest = todo_remove_test_override_date_sent
      # TODO: # REMOVE THIS HACK # REMOVE THIS HACK # REMOVE THIS HACK



      if parsed_id:
        this_record.spm_name = parsed_id['name']
        this_record.spm_serial = parsed_id['serial']
        this_record.spm_transaction = parsed_id['transaction']

      # if there's no date at all in this record, at least write the timestamp for
      # sorting purposes (checkout sometimes doesn't notify of payment
      # this_recordoperly or is super-delayed, so this hack is necessary)
      if not this_record.date_latest:
        this_record.date_latest = notification_timestamp

      # link this payment to an account.  GetSPMUserByEmail will force-create
      # a user with this information if it doesn't exist already
      if not this_record.SPMUser_buyer:
        um = spmuser.UserManager()
        this_record.SPMUser_buyer = um.GetSPMUserByEmail(notification_checkout_buyer_email)
      # if there isn't a user name for this user (i.e., this was just created
      # a few lines above), then let's this_recorde-populate it
      if not this_record.SPMUser_buyer.name:
        this_record.SPMUser_buyer.name = notification_checkout_buyer_name
        this_record.SPMUser_buyer.put()

      this_record.checkout_buyer_email = notification_checkout_buyer_email
      # this is only useful for helping backfill from non-spm stuff
      if not this_record.sent_to_email:
        this_record.sent_to_email = notification_checkout_buyer_email
      this_record.checkout_buyer_name = notification_checkout_buyer_name
      this_record.checkout_buyer_id = notification_checkout_buyer_id
      this_record.amount = notification_amount
      this_record.currency = notification_currency
      this_record.description = notification_description

      # try to identify and parse spmid
      spm_invoice_id = ''
      this_record.spm_url = spm_invoice_id


    elif notification_primary == 'charge-amount-notification':

      if not this_record:
        logging.error('(spmcheckout) Charge-amount-notificaiton found with no record in system.  This is most likely an ordering issue.')
      else:
        notification_date = self.__ParseCheckoutTime(notify['timestamp'])
        this_record.date_paid = notification_date
        if not this_record.date_latest or notification_date > this_record.date_latest:
          this_record.date_latest = notification_date

    elif notification_primary == 'refund-amount-notification':
  
      if not this_record:
        logging.error('(spmcheckout) Refund-amount-notification found with no record in system.  This is most likely an ordering issue.')
      else:
        notification_date = self.__ParseCheckoutTime(notify['timestamp'])
        this_record.date_cancelled = notification_date
        if not this_record.date_latest or notification_date > this_record.date_latest:
          this_record.date_latest = notification_date

    # perform a common set of updates
    if this_record:
      # this may blatantly re-overwrite these two fields, but there isn't any
      # situation where this doesn't make sense
      this_record.checkout_key = checkout_key
      this_record.checkout_merchant_id = self.spm_seller_user.checkout_merchant_id
      # populate 'sent to' with 'buyer' for non-spm-sent receipts (assumes that
      # the record was sent to whoever paid it since we have no other context)
      if not this_record.SPMUser_sentto and this_record.SPMUser_buyer:
        this_record.SPMUser_sentto = this_record.SPMUser_buyer
      # write
      this_record.put()


  def GetHistory(self, utc_start, utc_end):
    """Sends a request to google checkout using supplied arguments.
    """

    _REQUEST_FIRST_PAGE = """
      <?xml version="1.0" encoding="UTF-8"?>
      <notification-history-request xmlns="http://checkout.google.com/schema/2">
        <start-time>%(start)s</start-time>
        <end-time>%(end)s</end-time>
      </notification-history-request>"""

    _REQUEST_NEXT_PAGE = """
      <?xml version="1.0" encoding="UTF-8"?>
      <notification-history-request xmlns="http://checkout.google.com/schema/2">
        <next-page-token>%(token)s</next-page-token>
      </notification-history-request>"""
  
    # set up payload for initial request
    utc_start = utc_start.strftime(_CHECKOUT_UTC_FORMATTER)
    utc_end = utc_end.strftime(_CHECKOUT_UTC_FORMATTER)
    cur_payload = _REQUEST_FIRST_PAGE % ({
      'start': utc_start,
      'end': utc_end
    })

    # set up empty return list
    aggregate_list = []

    # make series of requests until no more next page tokens are returned
    while cur_payload:
      # individual request
      response = PostRequest(
        _CHECKOUT_NOTIFICATION_HISTORY_URL % ({
          'merchant_id': self.spm_seller_user.checkout_merchant_id}
        ),
        self.__CheckoutRequestHeaders(),
        cur_payload
      )
      if not response:
        return None

      # parse this response and append to return_list
      response = self.__ParseCheckoutSellerHistorySingleResponse(response)
      if response['notifications']:
        for notification in response['notifications'].keys():
          aggregate_list.append(response['notifications'][notification])

      # setup next request
      try:
        cur_payload = _REQUEST_NEXT_PAGE % ({'token': response['next-page-token']})
      except KeyError:
        cur_payload = None

    # sort basd on type
    new_order_list = []
    charged_list = []
    refund_list = []
    for notify in aggregate_list:
      # TODO this should probably be db.run_in_transaction(self.__ApplyTransaction, notify)
      notification_primary = notify['sopay-me/google-type']
      if notification_primary == 'new-order-notification':
        new_order_list.append(notify)
      elif notification_primary == 'charge-amount-notification':
        charged_list.append(notify)
      elif notification_primary == 'order-state-change-notification':
        pass
      elif notification_primary == 'risk-information-notification':
        pass
      elif notification_primary == 'refund-amount-notification':
        refund_list.append(notify)
      else:
        logging.warning('Unexpected primary_type in parsing checkout response')
        logging.warning(str(notification_primary))
        logging.warning(str(notify))

    # do new order notification first to avoid checkout id collisions (we want
    # the record to be in the system with details first before we update it)
    for notify in new_order_list:
      self.__ApplyTransaction(notify)
    for notify in charged_list:
      self.__ApplyTransaction(notify)      
    for notify in refund_list:
      self.__ApplyTransaction(notify)
    
    
    # store that we've just synced this
    self.spm_seller_user.checkout_last_sync = datetime.utcnow()
    self.spm_seller_user.put()
    
    # return list for debug dumps
    return aggregate_list


  def GetPaymentUrl(self, spm_full_id, description, amount, currency='USD'):
    """Sends checkout payment
    
    http://code.google.com/apis/checkout/developer/Google_Checkout_XML_API.html#checkout_api"""

    # TODO support mulitiple items per cart for aggregation
    _ONE_ITEM_CART = """
      <?xml version="1.0" encoding="UTF-8"?>

      <checkout-shopping-cart xmlns="http://checkout.google.com/schema/2">
        <shopping-cart>
          <items>
            <item>
              <item-name>%(name)s</item-name>
              <item-description>%(description)s</item-description>
              <unit-price currency="%(currency)s">%(amount)s</unit-price>
              <quantity>%(quantity)s</quantity>
              <digital-content>
                <display-disposition>OPTIMISTIC</display-disposition>
                <description>Your payment has been sent.</description>
              </digital-content>
              <merchant-item-id>%(public_id)%</merchant-item-id>
              <merchant-private-item-data>%(private_id)s</merchant-private-item-data>
            </item>
          </items>
        </shopping-cart>
      </checkout-shopping-cart>
    """

    payload = _ONE_ITEM_CART % ({
      'name': SPM_ORDER_ITEM,
      'description': description,
      'currency': currency,
      'amount': amount,
      'quantity': 1,
      'public_id': spm_full_id,
      'private_id': spm_full_id,
    })

    response = PostRequest(
      _CHECKOUT_API_URL % ({'merchant_id': self.spm_seller_user.checkout_merchant_id}),
      self.__CheckoutRequestHeaders(),
      payload
    )
    
    if not response:
      return None
    
    redirect_url = self.__ParseCheckoutCartResponse(response)
    return redirect_url
    













