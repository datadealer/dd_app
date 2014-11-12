"""Data Dealer backend application.

.. todo:: more documentation
"""

from pyramid.config import Configurator

from pyramid_beaker import set_cache_regions_from_settings
from dd_app.jsonrpc import jsonrpc
from dd_app.connections import MongoConnector, DDMongoConnector, DDRedisConnector
from dd_app.render import DDJSONRenderer
from dd_app.socket.sessions import DDSockJSSession

def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    set_cache_regions_from_settings(settings)
    config = Configurator(settings=settings)
    config.include(jsonrpc)
    config.add_renderer('ddjson', DDJSONRenderer)
    config.registry.settings['mongodb.connector'] = DDMongoConnector(settings['mongodb.uri'], settings['mongodb.db'], settings['mongodb.users'])
    if settings.get('mongodb_log.uri', None) is not None:
        config.registry.settings['logdb.connector'] = MongoConnector(settings['mongodb_log.uri'], settings['mongodb_log.db'])
    config.registry.settings['redis.connector'] = DDRedisConnector(settings['redis.host'], settings['redis.port'], settings['redis.db'], password=settings.get('redis.pass', None))
    config.include('pyramid_sockjs')
    #config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_route('home', '/app/')
    config.add_jsonrpc_endpoint('api', '/app/api/', default_renderer='ddjson')
    config.add_sockjs_route(prefix='/__sockjs__', session=DDSockJSSession, sockjs_cdn='https://beta.datadealer.com/sockjs-0.3.4.min.js', cookie_needed=False)
    config.scan()
    return config.make_wsgi_app()
