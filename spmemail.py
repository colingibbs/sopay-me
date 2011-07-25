from google.appengine.api import mail

# http://code.google.com/appengine/docs/python/mail/sendingmail.html

class SPMEmailManager():
  """Sends email when a charge has been sent."""

  def __init__(self, from_name, from_email):
    if not from_name:
      from_name = ''
    self.sender_string = from_name + ' <' + from_email + '>'
    self.from_name = from_name


  def ConstructEmailText(self, to_name):
    """A separate construct public function for previewing."""

    _EMAIL_TEXT = \
"""Hey %(to_name)s,

%(from_name)s says sopay.me!

- the sopay.me team
"""

    return _EMAIL_TEXT % ({
      'to_name': to_name,
      'from_name': self.from_name,
    })


  def ConstructEmailHTML(self, to_name):
    """A separate construct public function for previewing."""

    _EMAIL_HTML = \
"""<html><head></head><body>
Hey %(to_name)s,

%(from_name)s says sopay.me!

- the sopay.me team
</body>
"""

    return _EMAIL_HTML % ({
      'to_name': to_name,
      'from_name': self.from_name,
    })


  def SendEmail(self, to_name, to_email):

    if not to_name:
      to_name = ''
    if not to_email:
      loggin.critical('SendEmail called without to_email')
      return

    to_string = to_name + ' <' + to_email + '>'

    message = mail.EmailMessage(
      sender = self.sender_string,
      to = to_string,
      subject = self.from_name + ' says sopay.me!',
      body = self.ConstructEmailText(to_name),
      html = self.ConstructEmailHTML(to_name),
    )

    message.send()
