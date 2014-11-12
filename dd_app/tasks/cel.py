from celery import Celery
from celery.signals import worker_init

from dd_app.tasks import celeryconfig

@worker_init.connect
def bootstrap_pyramid(signal, sender):
    from pyramid.paster import bootstrap
    ini_path = getattr(celeryconfig, 'DD_PYRAMID_INI')
    sender.app.settings = bootstrap(ini_path)['registry'].settings
    # setup sentry logging
    dsn = getattr(celeryconfig, 'DD_SENTRY_DSN', None)
    if dsn is not None:
        from raven import Client
        client = Client(dsn=dsn)
        from raven.contrib.celery import register_signal
        register_signal(client)


celery = Celery()
celery.config_from_object(celeryconfig)
