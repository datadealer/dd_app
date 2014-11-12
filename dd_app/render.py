"""Collection of pyramid renderers used by Data Dealer"""

from pyramid.renderers import JSON
from bson.json_util import dumps

DDJSONRenderer = JSON(serializer=dumps)
"""pyramid.renderers.JSON using bson.json_util for serialization"""
#DDJSONRenderer.add_adapter(datetime.datetime, lambda v, r: v.isoformat())
