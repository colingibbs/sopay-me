from google.appengine.api import mail

# http://code.google.com/appengine/docs/python/mail/sendingmail.html

class SPMEmailManager():
  """Sends email when a charge has been sent."""

  def __init__(self, from_name, from_email):
    if not from_name:
      from_name = ''
    self.sender_string = from_name + ' <' + from_email + '>'
    self.from_name = from_name


  def SendEmail(self, to_name, to_email, spm_for, spm_url, pay_url, description, amount, reminder):

      _EMAIL_HTML = \
"""<div style="font-family: arial, sans-serif">
<div style="font-size: 13px; color: #333;">
<br/>
Hey %(to_name)s,
<br/><br/>
%(first_sentence)s
<br/><br/>
<div style="border: 1px solid #E5E5E5; padding: 8px;">
<span style="font-family: Palatino Linotype, Book Andiqua, Palatino, serif; padding-left: 4px; font-size: 15px;">$%(amount)s</span>
&nbsp;&nbsp;
<span style="font-style: italic;">%(desc)s</span>
</div>
<br/>
<a href="%(pay_url)s">Pay now using Google Checkout</a>
<br/><br/>
Want someone else to pay for you?  Point them at <a href="%(spm_url)s">%(spm_url)s</a>.
<br/><br/>
Thanks!
<br/>
- The team at <a href="www.sopay.me">sopay.me</a>
<br/><br/>
</div>
</div>"""

	#subject and first sentence change if this is the first email or a reminder
    if reminder
      set_subject = 'You still haven\'t paid' + self.from_name
	  first = 'You still haven\'t paid %(from_name)s for %(spm_for)s, ya bum!'
	else
	  set_subject = self.from_name + ' says sopay.me!'
	  first = '%(from_name)s says "so pay me for %(spm_for)s!"'
	
	first_sentence = first % ({
	  'from_name': self.from_name,
      'spm_for': spm_for,
	})

    if not to_name:
      to_name = ''
    if not to_email:
      loggin.critical('SendEmail called without to_email')
      return

    to_string = to_name + ' <' + to_email + '>'

    html_message = _EMAIL_HTML % ({
      'to_name': to_name,
      'first_sentence': first_sentence,
      'spm_url': spm_url,
      'pay_url': pay_url,
      'desc': description,
      'amount': amount,
    })

    message = mail.EmailMessage(
      sender = self.sender_string,
      to = to_string,
      subject = set_subject,
      html = (
        '<html><head></head><body>' + html_message + '</body>'
      )
    )

    message.send()
