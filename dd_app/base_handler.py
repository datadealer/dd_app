"""Request handler base classes
"""

from decorator import decorator
from pyramid.httpexceptions import HTTPForbidden

from dd_app.django_codec import DjangoSessionCodec
from dd_app.messaging.mixins import MsgMixin

class DDHandler(object):
    """Base view handler object
    """

    def __init__(self, request, *args, **kwargs):
        self.request = request

    @property
    def mongo(self):
        if not hasattr(self, '__mongo'):
            self.__mongo = self.settings['mongodb.connector']
        return self.__mongo

    @property
    def redis(self):
        if not hasattr(self, '__redis'):
            self.__redis = self.settings['redis.connector']
        return self.__redis

    @property
    def settings(self):
        return self.request.registry.settings

    @property
    def cookies(self):
        return self.request.cookies

    @property
    def debug_charge_accel(self):
        return int(self.settings.get('dd_app.debug_charge_accel', 1))

    @property
    def powerup_types(self):
        return ('ad', 'teammember', 'upgrade')


class DjangoSessionMixin(object):
    """Mixin implementing authentication agains django sessions"""

    def _get_redis_key(self, key):
        return "%s%s" % (self.settings['session.prefix'], key)

    @property
    def session_codec(self):
        if not hasattr(self, '_session_codec'):
            self._session_codec = DjangoSessionCodec(self.settings)
        return self._session_codec

    def get_session_cookie(self):
        if hasattr(self, '_token'):
            return self._token
        return self.cookies.get(self.settings['session.cookie_id'], None)

    def get_redis_session(self, key):
        self._raw_session = self.redis.get().get(self._get_redis_key(key))
        result = self._raw_session
        return result

    def _get_session_data(self):
        key = self.get_session_cookie()
        if key is None:
            return {} # no session cookie
        session_data = self.get_redis_session(key)
        if session_data is None:
            return {} # no session data for key
        session_dec, auth_uid = self.session_codec.decode(session_data)
        return session_dec

    @property
    def session_data(self):
        if not hasattr(self, '_django_session'):
            self._django_session = self._get_session_data()
        return self._django_session

    @property
    def session_language(self):
        return self.session_data.get('django_language', 'en')

    @property
    def auth_uid(self):
        return self.session_data.get('_auth_user_id', None)

    def check_user(self):
        if self.auth_uid is not None:
            return self.mongo.get_user_by_auth_uid(self.auth_uid, {'_id': 1}) is not None
        return False

    def get_user_info(self):
        if self.auth_uid is not None:
            return self.mongo.get_user_by_auth_uid(self.auth_uid)

    @property
    def userdata(self):
        if not hasattr(self, '_userdata'):
            self._userdata = self.get_user_info()
        return self._userdata

    @property
    def game_query_base(self):
        oid = self.userdata['_id']
        query_base = {'user.$id': oid}
        version = self.userdata.get('game_version', None)
        if version is not None:
            query_base.update({'version': version})
        return query_base

    def _delete_session(self):
        del self._django_session
        del self._raw_session
        if hasattr(self, '_delkey'):
            self.redis.get().delete(self._get_redis_key(self._delkey))
            del self._delkey

    def _delete_cookie(self):
        def del_cookie_callback(request, response):
            response.delete_cookie(self.settings['session.cookie_id'])
        self.request.add_response_callback(del_cookie_callback)

    def _logout(self):
        self._delkey = self.get_session_cookie()
        self._delete_cookie()
        self._delete_session()

    def get_game_version(self, auth_uid):
        if not hasattr(self, '_game_version'):
            data = self.mongo.get_game_version(auth_uid)
            if data is None:
                self._game_version = None
            else:
                self._game_version = data.get('game_version', None)
        return self._game_version


class BaseHandler(DDHandler, DjangoSessionMixin, MsgMixin):

    def _get_uid(self):
        # For MsgMixin compatibility
        return self.auth_uid

# decorator preserving the argspec, 
# see https://micheles.googlecode.com/hg/decorator/documentation.html
@decorator
def dd_protected(f, obj, token, *args, **kwargs):
    obj._token = token
    if obj.auth_uid is None:
        raise HTTPForbidden('unauthorized')
    return f(obj, token, *args, **kwargs)
