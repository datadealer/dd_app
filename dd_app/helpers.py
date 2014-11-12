"""
Helper functions
"""

import datetime
import math
import pytz
import random
import re

def calculateAP(snap_val, snap_dt, levelinfo, datenow=None):
    if datenow is None:
        datenow = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
    period = datenow - snap_dt
    increments = int(math.ceil(period.total_seconds()*1000)) // levelinfo['ap_inc_interval']
    update_dt = snap_dt + datetime.timedelta(milliseconds=increments*levelinfo['ap_inc_interval'])
    ap = max(0, min(snap_val + (increments * levelinfo['ap_inc_value']), levelinfo['ap_max']))
    return (ap, update_dt)

class WeightedRandomizer:
    """simple weighted randomizer by Hyperboreus
    https://stackoverflow.com/a/14993631"""

    def __init__ (self, weights):
        self.__max = .0
        self.__weights = []
        for value, weight in weights.items ():
            self.__max += weight
            self.__weights.append ( (self.__max, value) )

    def random (self):
        r = random.random () * self.__max
        for ceil, value in self.__weights:
            if ceil > r: return value

def validateDisplayName(display_name):
    display_name = display_name.strip()
    if len(display_name)<1 or len(display_name)>32:
        return None
    matchr = re.compile(r'^[ \w-]+$', re.U | re.I)
    if matchr.match(display_name) is None:
        return None
    return display_name
