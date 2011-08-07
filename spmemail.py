from google.appengine.api import mail

# http://code.google.com/appengine/docs/python/mail/sendingmail.html

class SPMEmailManager():
  """Sends email when a charge has been sent."""

  def __init__(self, from_name, from_email):
    if not from_name:
      from_name = ''
    self.sender_string = from_name + ' <' + from_email + '>'
    self.from_name = from_name


  def SendEmail(self, to_name, to_email, spm_for, spm_url, pay_url, description):

    _EMAIL_HTML = \
"""Hey %(to_name)s,<br/>
<br/>
%(from_name)s says "so pay me for %(spm_for)s!"<br/>
<br/>
%(desc)s<br/>
<br/>
<a href="%(pay_url)s">Pay now</a> using Google checkout.<br/>
<br/>
Or check out who else has paid at <a href="%(spm_url)s">%(spm_url)s</a><br/>
<br/>
Thanks,<br/>
- the sopay.me team<br/>
"""

    if not to_name:
      to_name = ''
    if not to_email:
      loggin.critical('SendEmail called without to_email')
      return

    to_string = to_name + ' <' + to_email + '>'

    html_message = _EMAIL_HTML % ({
      'to_name': to_name,
      'from_name': self.from_name,
      'spm_for': spm_for,
      'spm_url': spm_url,
      'pay_url': pay_url,
      'desc': description,
    })

    message = mail.EmailMessage(
      sender = self.sender_string,
      to = to_string,
      subject = self.from_name + ' says sopay.me!',
      html = (
        '<html><head></head><body>' + html_message + '</body>'
      )
    )

    message.send()
