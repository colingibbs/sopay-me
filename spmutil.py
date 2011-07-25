"""Constant lists, URLFetch wrapper and retryer."""

import logging

from google.appengine.ext import db
from google.appengine.api import urlfetch
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app


################################################################################


SPM = 'sopay.me'
SPM_ORDER_ITEM = 'sopay.me for'

_SPM_PATH_PREFIX = '/for/'
_SPM_FULL_PREFIX = 'sopay.me' + _SPM_PATH_PREFIX
_MAX_TRIES = 2


################################################################################


def GetRequest(url):

  keep_trying = True;
  try_count = 0;

  while keep_trying:

    try:
      response = urlfetch.fetch(
        url = url,
        method = urlfetch.GET
      )
    except urlfetch.SSLCertificateError:
      pass

    # nothing returned, that's not supposed to happen... so try again
    if not response:
      logging.warning('URLFetch empty at try ' + str(try_count) + '/' +
          str(_MAX_TRIES) + '.')

    # anything besides 200 isn't what we're expecting, so try again
    elif not response.status_code == 200:
      logging.warning('URLFetch status != 200 at try ' + str(try_count) + '/' +
          str(_MAX_TRIES) + '.  Error' + str(response.status_code) + '. \n' +
          response.content)
  
    # guess everything's good at this point
    if response.status_code == 200:
      return response.content
      
    try_count += 1
    if try_count > _MAX_TRIES:
      logging.error('URLFetch reached max_tries=' + str(try_count) +
          '.  Giving up!  :(')
      keep_trying = False
      return None


def PostRequest(url, headers, payload):

  keep_trying = True;
  try_count = 0;

  while keep_trying:

    try:
      response = urlfetch.fetch(
        url = url,
        method = urlfetch.POST,
        headers = headers,
        payload = payload
      )
    except urlfetch.SSLCertificateError:
      logging.warning('URLFetch SSL Certificate error')
      response = None

    # nothing returned, that's not supposed to happen... so try again
    if not response:
      logging.warning('URLFetch empty at try ' + str(try_count) + '/' +
          str(_MAX_TRIES) + '.')

    # anything besides 200 isn't what we're expecting, so try again
    elif not response.status_code == 200:
      logging.warning('URLFetch status != 200 at try ' + str(try_count) + '/' +
          str(_MAX_TRIES) + '.  Error' + str(response.status_code) + '. \n' +
          response.content)
  
    # guess everything's good at this point
    elif response.status_code == 200:
      return response.content
      
    try_count += 1
    if try_count > _MAX_TRIES:
      logging.error('URLFetch reached max_tries=' + str(try_count) +
          '.  Giving up!  :(')
      keep_trying = False
      return None


def ParseSPMURL(spmid, relpath=False):
  """Returns none if there is a parse error."""

  if not spmid:
    return None

  if relpath:
    match_string = _SPM_PATH_PREFIX
  else:
    match_string = _SPM_FULL_PREFIX

  match_length = len(match_string)

  # quick sanity checks
  if len(spmid) <= match_length:
    return None
  if not spmid[0:match_length] == match_string[0:match_length]:
    return None

  # parse path
  rest = spmid[match_length:]
  rest = rest.split('/')

  # this needs to be 2 or three long
  if len(rest) < 2 or len(rest) > 3:
    return None
  if not rest[1].isdigit():
    return None

  if len(rest) == 3:
    transaction = long(rest[2])
  else:
    transaction = None

  return {
    'c14n': BuildSPMURL(rest[0], rest[1], relpath),
    'name': rest[0],
    'serial': long(rest[1]),
    'transaction': transaction,
  }


def ParseSPMID(spmid, relpath=False):
  """Calls ParseSPMURL, but also returns None if 'transaction' is not present"""

  return_value = ParseSPMURL(spmid)
  if not return_value:
    return None
  if return_value['transaction'] == None: # explicit none check because 0 is ok
    return None
  
  return return_value


def BuildSPMURL(name, serial, transaction=None, relpath=False):

  if name == None or serial == None:
    return None
  if type(serial) is str:
    if not serial.isdigit():
      return None

  if relpath:
    spm_prefix = _SPM_PATH_PREFIX
  else:
    spm_prefix = _SPM_FULL_PREFIX

  serial = long(serial)
  if serial < 0:
    return None
  elif serial < 10:
    serial_string = '00' + str(serial)
  elif serial < 100:
    serial_string = '0' + str(serial)
  else:
    serial_string = str(serial)

  return spm_prefix + name + '/' + serial_string



def BuildSPMID(name, serial, transaction):
  """Calls BuildSPMURL and performs additonal transaction encoding."""

  spm_base_url = BuildSPMURL(name, serial, relpath=False)

  if not spm_base_url:
    return None

  return spm_base_url + '/' + str(long(transaction))


def MakeAncestorFromSPMUser(spm_user):
  return db.Key.from_path('SPMUser', spm_user.key().id())
