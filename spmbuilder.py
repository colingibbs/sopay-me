import spmdb
from spmutil import *


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

    _MOBILE_HEADER = \
"""<!DOCTYPE HTML>
<html>
<head>
  <meta http-equiv="content-type" content="text/html; charset=utf-8">
  <meta name="HandheldFriendly" content="true" />
  <meta name="viewport" content="width=device-width, height=device-height, user-scalable=no" />
  <title>%(title)s</title>
  <link rel="stylesheet" type="text/css" href="/static/sopayme.css" />
  <link rel="stylesheet" type="text/css" href="/static/mobile.css" />
  <script type="text/javascript">
    var _gaq = _gaq || [];
    _gaq.push(['_setAccount', 'UA-17941280-2']);
    _gaq.push(['_trackPageview']);
    (function() {
      var ga = document.createElement('script'); ga.type = 'text/javascript'; ga.async = true;
      ga.src = ('https:' == document.location.protocol ? 'https://ssl' : 'http://www') + '.google-analytics.com/ga.js';
      var s = document.getElementsByTagName('script')[0]; s.parentNode.insertBefore(ga, s);
    })();
  </script>
</head>
<body>
  <div id="title"><div class="titletext boxl-content">%(title)s</div></div>
  <div class="compact titlesecondary">%(login)s</div>
"""

    _DESKTOP_HEADER = \
"""<!DOCTYPE HTML>
<html>
<head>
  <meta http-equiv="content-type" content="text/html; charset=utf-8">
  <title>%(title)s</title>
  <link rel="stylesheet" type="text/css" href="/static/sopayme.css" />
  <link rel="stylesheet" type="text/css" href="/static/desktop.css"" />
  <script type="text/javascript">
    var _gaq = _gaq || [];
    _gaq.push(['_setAccount', 'UA-17941280-2']);
    _gaq.push(['_trackPageview']);
    (function() {
      var ga = document.createElement('script'); ga.type = 'text/javascript'; ga.async = true;
      ga.src = ('https:' == document.location.protocol ? 'https://ssl' : 'http://www') + '.google-analytics.com/ga.js';
      var s = document.getElementsByTagName('script')[0]; s.parentNode.insertBefore(ga, s);
    })();
  </script>
</head>
<body>
  <div id="title" class="boxl-hparent">
    <div class="titletext boxl-content">%(title)s</div>
    <div class="boxl-spacer"></div>
    <div class="titlesecondary boxl-content">%(login)s</div>
  </div>"""

    _PAGE_FOOTER = \
"""<div class="fullline"></div>
</body>
<!-- Copyright 2011 sopay.me -->
"""

    render = []

    if self.is_mobile:
      render.append(_MOBILE_HEADER % {
        'title': self.title,
        'login': self.logged_in_text,
      })
    else:
      render.append(_DESKTOP_HEADER % {
        'title': self.title,
        'login': self.logged_in_text,
      })

    render.append('\n'.join(self.pagebuffer))
    render.append(_PAGE_FOOTER)

    return '\n'.join(render)

  
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

    __DESKTOP = \
"""%(opendiv_linestyle)s
  <div class="boxl-hparent">
    <div class="boxl-vparent boxl-content col-amount">
      <div class="boxl-spacer"></div>
      <div class="boxl-content"><span class="amount"><span class="currency">%(text_currency)s&nbsp;</span>%(text_amount)s</span></div>
      <div class="boxl-spacer"></div>
    </div>
    <div class="boxl-vparent boxl-content col-desc">
      <div class="boxl-spacer"></div>
      <div class="boxl-content text">%(text_description)s</div>
      <div class="boxl-content text shrinky">%(div_paid)s%(text_paid)s</div>
      <div class="boxl-spacer"></div>
    </div>
    <div class="boxl-vparent boxl-content col-face">
      <div class="boxl-spacer"></div>
      <div class="boxl-content profile40" style="background-image:url(\'%(url_seller_picture)s\');"></div>
      <div class="boxl-spacer"></div>
    </div>
    <div class="boxl-vparent boxl-content col-annotation">
      <div class="boxl-spacer"></div>
      <div class="boxl-content text shrinky">%(text_seller)s</div>
      <div class="boxl-content smalltext shrinky">%(text_email)s</div>
      <div class="boxl-spacer"></div>
    </div>
    <div class="boxl-vparent boxl-content col-paidbutton">
      <div class="boxl-spacer"></div>
      <div class="boxl-content text">%(text_paynow)s</div>
      <div class="boxl-spacer"></div>
    </div>
  </div>
</div>"""

    __MOBILE = \
"""%(opendiv_linestyle)s
  <div class="boxl-hparent">
    <div class="boxl-vparent boxl-content col-mobileleft">
      <div class="boxl-spacer"></div>
      <div class="boxl-content profile40" style="background-image:url(\'%(url_seller_picture)s\');"></div>
      <div class="boxl-spacer"></div>
    </div>
    <div class="boxl-vparent boxl-content col-mobileright">
      <div class="boxl-spacer"></div>
      <div class="boxl-content text shrinky"><span class="amount"><span class="currency">%(text_currency)s&nbsp;</span>%(text_amount)s</span></div>
      <div class="boxl-content text shrinky">%(text_seller)s <span class="smalltext">(%(text_email)s)</span></div>
      <div class="boxl-content text shrinky">%(text_description)s</div>
      <div class="boxl-content text shrinky">%(div_paid)s%(text_paid)s%(text_paynow)s</div>
      <div class="boxl-spacer"></div>
    </div>
  </div>
</div>"""

    if self.is_mobile:
      pagetext = __MOBILE
      if text_paynow:
        text_paynow = ' - ' + text_paynow
    else:
      pagetext = __DESKTOP

    self.pagebuffer.append(pagetext % {
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
    })


  def AppendCompact(self, message):
    _PAGE_INLINE_COMPACT = '<div class="compact">%(message)s</div>'
    self.pagebuffer.append(_PAGE_INLINE_COMPACT % ({'message': message}))


  def AppendSpaced(self, message):
    _PAGE_INLINE = '<div class="fullline">%(message)s</div>'
    self.pagebuffer.append(_PAGE_INLINE % ({'message': message}))


  def AppendText(self, message):
    _PAGE_INLINE = '<div class="simple">%(message)s</div>'
    self.pagebuffer.append(_PAGE_INLINE % ({'message': message}))
    
    
    