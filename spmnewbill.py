import logging # (fyi levels are debug, info, warning, error, critical) 
from google.appengine.ext import db

from spmutil import *


################################################################################


class NewBill():
  """Special interfaces with the database called from the API and web UI."""

  def ReserveNextSerial(self, name_to_reserve, number_to_reserve = 1):
    """Runs the transaction."""
    return db.run_in_transaction(
      self.__ReserveNextSerialsTransaction, name_to_reserve, number_to_reserve
    )


  def __ReserveNextSerialsTransaction(self, name_to_reserve, number_to_reserve):
    """Reserves the next serial numbers."""

    count_record = None
    count_records = db.GqlQuery(
      'SELECT * FROM CountStore WHERE ANCESTOR IS :1',
      db.Key.from_path('CountURL', name_to_reserve)
    ).fetch(limit=2)
    if len(count_records) == 1:
      count_record = count_records[0]
    elif len(count_records) >= 2:
      logging.critical('More than one record returned from ancestor query')

    if count_record:
      cur_count = count_record.url_count
      count_record.url_count = cur_count + number_to_reserve
      count_record.put()
      return cur_count
    else:
      new_record = spmdb.CountStore(
        parent = db.Key.from_path('CountURL', name_to_reserve),
        url_count = number_to_reserve
      )
      new_record.put()
      return 0