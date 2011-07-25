"""All integration with Google checkout is in this file."""

import base64
from datetime import datetime
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


  def __GetHistoryTransaction(self, notify):
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

    pr = None

    ##### identify which record to update #####

    checkout_key = notify['google-order-number']

    # easy update - checkout information already in system
    if not pr:
      existing_records = db.GqlQuery(
        'SELECT * FROM PurchaseRecord WHERE ANCESTOR IS :1 AND checkout_key = :2',
        MakeAncestorFromSPMUser(self.spm_seller_user), checkout_key
      ).fetch(limit=2)
      if len(existing_records) == 1:
        pr = existing_records[0]
      elif len(existing_records) >= 2:
        logging.critical('More than one record returned with same checkout_key')

    ##### extract all the data #####

    # switch extraction on notification type
    noteinfo_primary = notify['sopay-me/google-type']
    if noteinfo_primary == 'new-order-notification':
      
      # general information
      noteinfo_timestamp = self.__ParseCheckoutTime(notify['timestamp'])
      # purchase information
      noteinfo_amount = notify['order-total']
      noteinfo_currency = notify['order-total-currency']
      # get buyer information
      noteinfo_checkout_buyer_email = notify['buyer-billing-address']['email']
      noteinfo_checkout_buyer_name = notify['buyer-billing-address']['contact-name']
      noteinfo_checkout_buyer_id = notify['buyer-id']
      # get individual item information
      # TODO loop through all items and treat separately
      noteinfo_description = notify['shopping-cart']['items']['item1']['item-description']
      try:
        noteinfo_private_data = notify['shopping-cart']['items']['item1']['merchant-private-item-data']
      except KeyError:
        noteinfo_private_data = None



      # TODO: # REMOVE THIS HACK # REMOVE THIS HACK # REMOVE THIS HACK
      # used for testing locally on zach's desktop
      todo_remove_test_override_date_sent = None
      if noteinfo_primary == 'new-order-notification' and noteinfo_private_data:
        if noteinfo_private_data == 'sopay.me/for/TEST_20110720':
          noteinfo_private_data = 'sopay.me/for/duptest/000/' + noteinfo_amount[2]
          todo_remove_test_override_date_sent = datetime(2011, 1, 11, 1, 11)
          if noteinfo_amount == '0.77':
            noteinfo_checkout_buyer_email = 'zpm@google.com'
        elif noteinfo_private_data == '340101':
          noteinfo_private_data = 'sopay.me/for/test2/000/0'
          todo_remove_test_override_date_sent = datetime(2011, 2, 22, 2, 22)
        elif noteinfo_private_data == 'sopay.me/for/TEST_20110720_439':
          noteinfo_private_data = 'sopay.me/for/test3-nosend/000/0'
        elif noteinfo_private_data == 'sopay.me/for/TEST_20110720_number2':
          noteinfo_private_data = 'sopay.me/for/test4-nosend/000/0'
        elif noteinfo_private_data == 'sopay.me/for/Q':
          noteinfo_private_data = 'sopay.me/for/test5/000/0'
          todo_remove_test_override_date_sent = datetime(2011, 5, 5, 5, 5)
      # TODO: # REMOVE THIS HACK # REMOVE THIS HACK # REMOVE THIS HACK



      # if there's not yet a valid record but there is a valid spm name/serial, try
      # looking up based on that valid spm name/serial... if checkout key is
      # empty, then good... if not, then this is a duplicate of the same spm name/serial, 
      # so don't do anything and let the default creation flow run below...
      parsed_id = ParseSPMID(noteinfo_private_data)
      if not pr and parsed_id:
        existing_records = db.GqlQuery(
          'SELECT * FROM PurchaseRecord ' +
          'WHERE ANCESTOR IS :1 AND spm_name = :2 AND spm_serial = :3 ' + 
          'AND spm_transaction = :4 AND checkout_key = NULL',
          MakeAncestorFromSPMUser(self.spm_seller_user),
          parsed_id['name'], parsed_id['serial'], parsed_id['transaction']
        ).fetch(limit=2)
        if len(existing_records) == 1:
          # ensure that this record isn't earmarked to be paid by someone else
          # before we update it with this payment
          if existing_records[0].SPMUser_buyer:
            # match this record using our criteria
            logging.debug('Trying this')
            logging.debug(existing_records[0].SPMUser_buyer.email_list)
            logging.debug(noteinfo_checkout_buyer_email)
            logging.debug(existing_records[0].amount)
            logging.debug(noteinfo_amount)
            logging.debug(existing_records[0].currency)
            logging.debug(noteinfo_currency)   
            logging.debug(existing_records[0].description)
            logging.debug(noteinfo_description)
            if noteinfo_checkout_buyer_email in existing_records[0].SPMUser_buyer.email_list:
              if existing_records[0].amount == noteinfo_amount:
                if existing_records[0].currency == noteinfo_currency:
                  if existing_records[0].description == noteinfo_description:
                    pr = existing_records[0]
            else:
              pr = None # and follow creation flow below
          else:
            pr = existing_records[0]
        elif len(existing_records) >= 2:
          logging.critical('More than one record returned with same spm name/serial/transaction')

      # already checked to see if this checkout order was in the system or the
      # private data spm name/serial were in the system... and if neither of 
      # them were, just create the new order record
      if not pr:
        pr = spmdb.PurchaseRecord(
          parent = MakeAncestorFromSPMUser(self.spm_seller_user),
          SPMUser_seller = self.spm_seller_user.key()
        )

      # .... by this point pr definitely exists, so let the updating begin ....



      # TODO: # REMOVE THIS HACK # REMOVE THIS HACK # REMOVE THIS HACK
      # used for testing locally on zach's desktop
      if todo_remove_test_override_date_sent:
        if not pr.date_sent:
          pr.date_sent = todo_remove_test_override_date_sent
        elif todo_remove_test_override_date_sent > pr.date_sent:
          pr.date_sent = todo_remove_test_override_date_sent
        if not pr.date_latest:
          pr.date_latest = todo_remove_test_override_date_sent      
        elif todo_remove_test_override_date_sent > pr.date_latest:
          pr.date_latest = todo_remove_test_override_date_sent
      # TODO: # REMOVE THIS HACK # REMOVE THIS HACK # REMOVE THIS HACK



      if parsed_id:
        pr.spm_name = parsed_id['name']
        pr.spm_serial = parsed_id['serial']
        pr.spm_transaction = parsed_id['transaction']

      # if there's no date at all in this record, at least write this for
      # sorting purposes (checkout sometimes doesn't notify of payment
      # properly or is super-delayed, so this hack is necessary)
      if not pr.date_latest:
        pr.date_latest = noteinfo_timestamp

      # link this payment to an account.  GetSPMUserByEmail will force-create
      # a user with this information if it doesn't exist already
      if not pr.SPMUser_buyer:
        um = spmuser.UserManager()
        pr.SPMUser_buyer = um.GetSPMUserByEmail(noteinfo_checkout_buyer_email)
        # TODO: need to handle if this comes back None (2 accts with same email)
      else:
        logging.critical('This should not ever happen.')
      
      pr.checkout_buyer_email = noteinfo_checkout_buyer_email
      # this is only useful for helping backfill from non-spm stuff
      if not pr.sent_to_email:
        pr.sent_to_email = noteinfo_checkout_buyer_email
      pr.checkout_buyer_name = noteinfo_checkout_buyer_name
      # if there isn't a user name for this user (i.e., this was just created
      # a few lines above), then let's pre-populate it
      if not pr.SPMUser_buyer.name:
        pr.SPMUser_buyer.name = noteinfo_checkout_buyer_name
        pr.SPMUser_buyer.put()
      pr.checkout_buyer_id = noteinfo_checkout_buyer_id
      pr.amount = noteinfo_amount
      pr.currency = noteinfo_currency
      pr.description = noteinfo_description

      # try to identify and parse spmid
      spm_invoice_id = ''
      pr.spm_url = spm_invoice_id


    elif noteinfo_primary == 'charge-amount-notification':

      noteinfo_date_paid = self.__ParseCheckoutTime(notify['timestamp'])

      # already checked to see if this checkout order was in the system... if
      # it's not, we don't have any more metadata so we have no choice but to
      # just create a new record
      if not pr:
        pr = spmdb.PurchaseRecord(
          parent = MakeAncestorFromSPMUser(self.spm_seller_user),
          SPMUser_seller = self.spm_seller_user.key()
        )

      # .... by this point pr definitely exists, so let the updating begin ....

      pr.date_paid = noteinfo_date_paid
      if not pr.date_latest or pr.date_paid > pr.date_latest:
        pr.date_latest = pr.date_paid

    elif noteinfo_primary == 'order-state-change-notification':
      pass
    elif noteinfo_primary == 'risk-information-notification':
      pass
    else:
      logging.warning('Unexpected primary_type in parsing checkout response')

    # this may blatantly overwrite these two fields, but there isn't any
    # situation where this doesn't make sense
    if pr:
      pr.checkout_key = checkout_key
      pr.checkout_merchant_id = self.spm_seller_user.checkout_merchant_id
      pr.put()


  def GetHistory(self, utc_start, utc_end):
    """Sends a request to google checkout using supplied arguments.
  
    ARGS:
      merchant_id: string with merchant id number
      merchant_key: string with merchant auth key
  
    RETURNS:
      dict of all notifications
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

    # for each item in our aggregate list, add it to the data store
    for notify in aggregate_list:
      # TODO this should probably be db.run_in_transaction(self.__GetHistoryTransaction, notify)
      self.__GetHistoryTransaction(notify)
    
    # record that we've just synced this
    self.spm_seller_user.checkout_last_sync = datetime.utcnow()
    self.spm_seller_user.put()


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
    













