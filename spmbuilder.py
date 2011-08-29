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

    # set email obfuscation 
    if user:
      self.obfuscate_pii = False
    else:
      self.obfuscate_pii = True
    
    ### uideb controls ####
    # m: force mobile view
    # o: force email obfuscation

    if 'm' in uideb:
      self.is_mobile = True

    if 'o' in uideb:
      self.obfuscate_pii = True

    ### set variables ###
    
    self.title = title
    self.logged_in_text = '<a href="/signin">sign in</a>'
    if user:
      if user.google_account:
        if user.google_account.email():
          self.logged_in_text = user.google_account.email()

    # initialize the buffer
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


  def AppendIdentity(self, record, show_seller_instead=False):

    text_email = ''
    text_name = ''
    url_picture = ''

    if record.SPMUser_seller and show_seller_instead:
      text_email = str(record.SPMUser_seller.email)
      text_name = record.SPMUser_seller.name
      if record.SPMUser_seller.facebook_id:
        url_picture = 'http://graph.facebook.com/' + record.SPMUser_seller.facebook_id + '/picture?square'
    elif record.SPMUser_sentto:
      if record.sent_to_email:
        text_email = record.sent_to_email
      else:
        text_email = str(record.SPMUser_sentto.email)
      text_name = record.SPMUser_sentto.name
      if record.SPMUser_sentto.facebook_id:
        url_picture = 'http://graph.facebook.com/' + record.SPMUser_sentto.facebook_id + '/picture?square'
    else:
      logging.debug('(spmbuilder) Trying to render hover line, SPMUser_sentto is none.')
      url_picture = ''

    if not text_email:
      text_email = 'ERROR: No email'
    elif self.obfuscate_pii:
      text_email = self.__ObfuscateEmail(text_email)

    if text_name and self.obfuscate_pii:
      text_name = self.__ObfuscateName(text_name)
    elif not text_name:
      text_name = text_email
      if not text_name:
        text_name = 'ERROR: No user'

    # record

    text_description = 'Description unknown'
    if record.description:
      text_description = record.description

    _JUST_MONTH = '%B'
    _JUST_DAY = '%d'
    _PRETTY_TIME = '%B %d'
    _YMD_TIME = '%Y-%m-%d'

    date_sent = ''
    if record.date_sent:
      date_sent = 'Sent on ' + record.date_sent.strftime(_PRETTY_TIME)

    ### actually start rendering ###

    if self.is_mobile:
      path_file = 'templates/mobile_record_div.html'
    else:
      path_file = 'templates/desktop_record_div.html'

    path = os.path.join(os.path.dirname(__file__), path_file)

    template_values = {
      'opendiv_linestyle': '<div class="line-nohover">',
      'text_currency': '',
      'text_amount': '',
      'description_line1': text_description,
      'description_line2': date_sent,
      'url_picture': url_picture,
      'text_name': text_name,
      'text_email': text_email,
      'text_paynow': '',
    }

    self.pagebuffer.append(template.render(path, template_values))


  def AppendHoverRecord(self, record, linkify, show_seller_instead=False):

    text_email = ''
    text_name = ''
    url_picture = ''

    if record.SPMUser_seller and show_seller_instead:
      text_email = str(record.SPMUser_seller.email)
      text_name = record.SPMUser_seller.name
      if record.SPMUser_seller.facebook_id:
        url_picture = 'http://graph.facebook.com/' + record.SPMUser_seller.facebook_id + '/picture?square'
    elif record.SPMUser_sentto:
      if record.sent_to_email:
        text_email = record.sent_to_email
      else:
        text_email = str(record.SPMUser_sentto.email)
      text_name = record.SPMUser_sentto.name
      if record.SPMUser_sentto.facebook_id:
        url_picture = 'http://graph.facebook.com/' + record.SPMUser_sentto.facebook_id + '/picture?square'
    else:
      logging.debug('(spmbuilder) Trying to render hover line, SPMUser_sentto is none.')
      url_picture = ''

    if not text_email:
      text_email = 'ERROR: No email'
    elif self.obfuscate_pii:
      text_email = self.__ObfuscateEmail(text_email)

    if text_name and self.obfuscate_pii:
      text_name = self.__ObfuscateName(text_name)
    elif not text_name:
      text_name = text_email
      if not text_name:
        text_name = 'ERROR: No user'

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
      text_currency = '$ '

    text_paynow = ''
    if record.checkout_payurl and not record.date_paid:
      text_paynow = '<a href="' + record.checkout_payurl + '">Pay now</a>'

    #text_transaction = ''
    #if record.spm_transaction:
    #  text_transaction = str(record.spm_transaction)

    _JUST_MONTH = '%B'
    _JUST_DAY = '%d'
    _PRETTY_TIME = '%B %d'
    _YMD_TIME = '%Y-%m-%d'

    # paid information

    text_paid_by = ''
    if record.date_cancelled:
      text_paid = '<div class="icon maybe"></div>Cancelled'
    elif record.date_paid:
      text_paid = (
        '<div class="icon yes"></div>Paid on ' +
        record.date_paid.strftime(_JUST_MONTH) + ' ' +
        str(long(record.date_paid.strftime(_JUST_DAY)))
      )
      if record.SPMUser_buyer:
        if record.SPMUser_buyer.name:
          if self.obfuscate_pii:
            payname = self.__ObfuscateName(record.SPMUser_buyer.name)
          else:
            payname = record.SPMUser_buyer.name
          text_paid_by = 'by ' + payname
        elif record.SPMUser_buyer.email:
          if self.obfuscate_pii:
            payname = self.__ObfuscateEmail(record.SPMUser_buyer.email)
          else:
            payname = record.SPMUser_buyer.email
          text_paid_by = 'by ' + payname
    else:
      text_paid = '<div class="icon no"></div>Not paid'
      # not created with sopay.me and not paid (cancelled out-of-band)
      if not record.spm_name:
        text_paid_by = '(not sent with sopay.me)'

    # no hover on mobile
    if c14n_url and linkify:
      opendiv_linestyle = '<div class="line-hover" onclick="location.href=\'' + c14n_url + '\'">'
    else:
      opendiv_linestyle = '<div class="line-nohover">' 

    ### actually start rendering ###

    if self.is_mobile:
      path_file = 'templates/mobile_record_div.html'
    else:
      path_file = 'templates/desktop_record_div.html'

    path = os.path.join(os.path.dirname(__file__), path_file)

    template_values = {
      'opendiv_linestyle': opendiv_linestyle,
      'text_currency': text_currency,
      'text_amount': text_amount,
      'description_line1': text_paid,
      'description_line2': text_paid_by,
      'url_picture': url_picture,
      'text_name': text_name,
      'text_email': text_email,
      'text_paynow': text_paynow,
    }

    self.pagebuffer.append(template.render(path, template_values))


  def AppendLine(self, message):
    _PAGE_INLINE = '<div class="line">%(message)s</div>'
    self.pagebuffer.append(_PAGE_INLINE % ({'message': message}))


  def AppendLineShaded(self, message):
    _PAGE_INLINE_SHADED = '<div class="line-shaded">%(message)s</div>'
    self.pagebuffer.append(_PAGE_INLINE_SHADED % ({'message': message}))
    

  def __ObfuscateEmail(self, email):
    """Obfuscates emails."""

    if not email:
      return ''

    parts = email.split('@')
    if parts[0]:
      if len(parts[0]) > 3:
        parts[0] = parts[0][0:3] + '***'
    if parts[1]:
      if len(parts[1]) > 3:
        parts[1] = parts[1][0:3] + '***'
  
    return parts[0] + '@' + parts[1]
  

  def __ObfuscateName(self, full_name):
    """Obfuscates full names by returning first name only."""

    if not full_name:
      return ''

    parts = full_name.split(' ')
    if parts[0]:
      return parts[0]
    else:
      return ''
