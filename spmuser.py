from datetime import datetime # tracking logins
import logging # DEBUG, INFO, WARNING, ERROR, CRITICAL

from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

# local imports
from spmutil import *

# TODO remove when we remove zachhack
import spmdb
import spmcheckout
from datetime import datetime, timedelta


################################################################################


class UserManager():


  def __NewSPMUserFromEmail(self, email):

    spm_user = spmdb.SPMUser()

    logging.info('Creating new SPMUser with email: ' + email)
    spm_user.email = email
    spm_user.put()

    # create
    return spm_user


  def GetSPMUserByEmail(self, email, create_new = True):

    spm_user = None
    userlist = db.GqlQuery(
      'SELECT * FROM SPMUser WHERE email = :1', email
    ).fetch(limit=2)

    if len(userlist) == 1:
      spm_user = userlist[0]
    elif len(userlist) == 0 and create_new:
      spm_user = self.__NewSPMUserFromEmail(email = email)
    elif len(userlist) == 0 and not create_new:
      pass
      # logging.debug('Choosing not to create user, returning None')
    else:
      logging.critical('Query returned more than one account with email.')

    return spm_user


  def __GetSPMUserByGoogleAccount(self, google_account, create_new = True):
    """TODO"""

    # google accounts login check
    if not google_account:
      return None

    spm_user = None
    userlist = db.GqlQuery(
      'SELECT * FROM SPMUser WHERE email = :1', google_account.email()
    ).fetch(limit=2)

    if len(userlist) == 1:
      spm_user = userlist[0]

    elif len(userlist) == 0 and create_new:
      # check to see if we already have an implicit account with that address,
      # and if not, just create one with that address
      logging.info('Using implicit login to create new account [' + google_account.email() + ']')
      spm_user = self.GetSPMUserByEmail(google_account.email(), create_new = True)

    elif len(userlist) == 0 and not create_new:
      logging.debug('Choosing not to create user [' + google_account.email() + '] returning None')

    else:
      logging.critical('Query for [' + google_account.email() + '] returned more than one google_account.')
  
    if spm_user:
      # make sure google account is linked
      if not spm_user.google_account:
        logging.info('Also linking google account to existing SPMUser [' + google_account.email() + ']')
        spm_user.google_account = google_account
      spm_user.last_login = datetime.utcnow()
      spm_user.put()

    return spm_user


  def GetSPMUser(self, sudo_email):
    """Performs login check.  Overrides if sudo specified and the current user
    is an admin.  Returns spm_user db object."""

    spm_loggedin_user = self.__GetSPMUserByGoogleAccount(users.get_current_user())
    if users.is_current_user_admin():
      if sudo_email:
        sudo_user = self.GetSPMUserByEmail(sudo_email, create_new = False)
        if sudo_user:
          spm_loggedin_user = sudo_user
    return spm_loggedin_user
    