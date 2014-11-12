"""
Helpers to decode/encode session data
"""

import base64
import cPickle as pickle
from django.utils.crypto import salted_hmac, constant_time_compare

class InvalidHash(Exception):
    """Exception raised when hash signature in session cookie fails to verify"""
    pass

class DjangoSessionCodec(object):
    """Encodes/decodes django 1.4 session data
    """
    uid_key = '_auth_user_id'

    def __init__(self, settings, **kwargs):
        self.django_key_salt = kwargs.get('django_key_salt', settings['django.key_salt'])
        self.django_secret = kwargs.get('django_secret', settings['django.secret'])

    def _hash(self, value):
        return salted_hmac(self.django_key_salt, value, secret=self.django_secret).hexdigest()

    def decode(self, session_data):
        encoded_data = base64.decodestring(session_data)
        new_hash, pickled = encoded_data.split(':', 1)
        expected_hash = self._hash(pickled)
        if not constant_time_compare(new_hash, expected_hash):
            raise InvalidHash('Invalid hash. Got %s, expected %s.' % (new_hash, expected_hash))
            decoded = {}
        else:
            decoded = pickle.loads(pickled)
        return (decoded, decoded.get(self.uid_key, None))

    def encode(self, session_dict):
        pickled = pickle.dumps(session_dict, pickle.HIGHEST_PROTOCOL)
        new_hash = self._hash(pickled)
        return base64.encodestring("%s:%s" % (new_hash, pickled))
