import spmdb
from spmutil import *

import os
from google.appengine.ext.webapp import template


################################################################################


class NewPage():

  def __init__(self, title, user, useragent, uideb):
    """Initializes a new page with useragent (to detect mobile or not)."""

    # set is_mobile based on useragent.  TODO: expand this to be more intelligent
    if 'android' in useragent.lower() or 'iphone' in useragent.lower():
      self.is_mobile = True
    else:
      self.is_mobile = False
    
    # override mobile setting if uideb=m present
    if 'm' in uideb:
      self.is_mobile = True
    
    self.title = title
    self.logged_in_text = 'Not logged in.'
    if user:
      if user.google_account.email():
        self.logged_in_text = user.google_account.email()

    # clear the buffer
    self.pagebuffer = []


  def Render(self):

    if self.is_mobile:
      path_file = 'templates/mobile.html'
    else:
      path_file = 'templates/desktop.html'

    path = os.path.join(os.path.dirname(__file__), path_file)

    template_values = {
      'title': self.title,
      'login': self.logged_in_text,
      'body_content': '\n'.join(self.pagebuffer),
    }

    return template.render(path, template_values)

  
  def AppendHoverRecord(self, record, linkify):

    # user
  
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
      logging.debug('(spmbuilder) Trying to render hover line, SPMUser_sentto is none.')
      text_seller = 'ERROR: No user found'
      text_email = 'ERROR: No user found'
      url_seller_picture = ''

    # record

    c14n_url = BuildSPMURL(record.spm_name, record.spm_serial, relpath=True)

    #if record.date_sent:
    #  text_sent = 'Sent on ' + record.date_sent.strftime(_PRETTY_TIME)
    #  div_sent = '<div class="icon yes"></div>'
    #else:
    #  text_sent = '<span class="maybetext">Not from ' + SPM + '</span>'
    #  div_sent = '<div class="icon maybe"></div>'

    text_description = 'Description unknown'
    if record.description:
      text_description = record.description

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
      text_paynow = '<a href="' + record.checkout_payurl + '"><strong>Pay now</strong></a>'

    #text_transaction = ''
    #if record.spm_transaction:
    #  text_transaction = str(record.spm_transaction)

    _JUST_MONTH = '%B'
    _JUST_DAY = '%d'
    _PRETTY_TIME = '%B %d'
    _YMD_TIME = '%Y-%m-%d'

    # paid information

    if record.date_cancelled:
      text_paid = 'Cancelled'
      div_paid = '<div class="icon maybe"></div>'
    elif record.date_paid:
      text_paid = (
        'Paid on ' + record.date_paid.strftime(_JUST_MONTH) + ' ' +
         str(long(record.date_paid.strftime(_JUST_DAY)))
      )
      div_paid = '<div class="icon yes"></div>'
      if record.SPMUser_buyer:
        if record.SPMUser_buyer.name:
          text_paid += ' by ' + record.SPMUser_buyer.name
        elif record.SPMUser_buyer.email:
          text_paid += ' by ' + record.SPMUser_buyer.email
    else:
      # created with sopay.me and not paid
      if record.spm_name:
        text_paid = 'Not paid'
        div_paid = '<div class="icon no"></div>'
      # not created with sopay.me and not paid (cancelled out-of-band)
      else:
        text_paid = 'Not paid, not from sopay.me'
        div_paid = '<div class="icon maybe"></div>'

    # no hover on mobile
    if c14n_url and linkify:
      opendiv_linestyle = '<div class="linehover" onclick="location.href=\'' + c14n_url + '\'">'
    else:
      opendiv_linestyle = '<div class="linenohover">' 

    ### actually start rendering ###

    if self.is_mobile:
      if text_paynow:
        text_paynow = ' - ' + text_paynow
      path_file = 'templates/mobile_div.html'
    else:
      path_file = 'templates/desktop_div.html'

    path = os.path.join(os.path.dirname(__file__), path_file)

    template_values = {
      'opendiv_linestyle': opendiv_linestyle,
      'text_currency': text_currency,
      'text_amount': text_amount,
      'text_description': text_description,
      'div_paid': div_paid,
      'text_paid': text_paid,
      'url_seller_picture': url_seller_picture,
      'text_seller': text_seller,
      'text_email': text_email,
      'text_paynow': text_paynow,
    }

    self.pagebuffer.append(template.render(path, template_values))


  def AppendCompact(self, message):
    _PAGE_INLINE_COMPACT = '<div class="compact">%(message)s</div>'
    self.pagebuffer.append(_PAGE_INLINE_COMPACT % ({'message': message}))


  def AppendSpaced(self, message):
    _PAGE_INLINE = '<div class="fullline">%(message)s</div>'
    self.pagebuffer.append(_PAGE_INLINE % ({'message': message}))


  def AppendText(self, message):
    _PAGE_INLINE = '<div class="simple">%(message)s</div>'
    self.pagebuffer.append(_PAGE_INLINE % ({'message': message}))
    
    
    