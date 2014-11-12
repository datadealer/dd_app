# Backends
BROKER_URL = 'redis://localhost:6379/3'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/3'
# Transport options
BROKER_TRANSPORT_OPTIONS = {'visibility_timeout': 86400}
# Result expiration
CELERY_TASK_RESULT_EXPIRES = 3600
# Timezome handling
CELERY_TIMEZONE = 'Europe/Vienna'
CELERY_ENABLE_UTC = True
 
# Where to get the tasks from?
CELERY_IMPORTS = ['dd_app.tasks.tasks',]
 
## DD Specific
import os
DD_APP_PATH = os.path.dirname(os.path.abspath(__file__))
DD_PYRAMID_INI = os.path.join(DD_APP_PATH, '../../local.ini')
 
CELERY_ACCEPT_CONTENT = ['pickle', 'json', 'msgpack']
