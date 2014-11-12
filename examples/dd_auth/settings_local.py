DEBUG=True
TEMPLATE_DEBUG = DEBUG

SECRET_KEY = 'vwOUZG4mjHWACGk6f8mc4CT1qASBSCoAyPTimWGcDDMaah3gyZ' # Make sure to provide your own unique key

### DATABASE SETTINGS

DATABASES = {
        'default': {
                    'ENGINE': 'django.db.backends.postgresql_psycopg2', # Example for a PostgreSQL backend
                    'NAME': 'dd_auth', # database name
                    'USER': 'dd_auth', # database user
                    'PASSWORD': 'HereComesYourPassword', # database password
                    'HOST': '',                             # Set to empty string for localhost.
                    'PORT': '',                             # Set to empty string for default.
                }
}

### EMAIL SETTINGS

EMAIL_HOST='my.mail.relay'
EMAIL_PORT='25'
EMAIL_HOST_USER='dd_auth_sender'
EMAIL_HOST_PASSWORD='dd_auth_sender_password'
EMAIL_USE_TLS=True

DEFAULT_FROM_EMAIL=SERVER_EMAIL='dd@yourdomain.com'

### REDIS SESSION STORE SETTINGS

SESSION_REDIS_HOST = 'localhost'
SESSION_REDIS_PORT = 6379
SESSION_REDIS_DB = 0
#SESSION_REDIS_PASSWORD = 'password' # set this if using auth

### MONGODB SETTINGS

DD_MONGO_DB = {
#    'host': 'mongodb://mongo_user:mongo_password@localhost/datadealer', # if you use auth
    'host': 'localhost', # no auth
    'port': 27017,
    'max_pool_size': 32,
    'db': 'datadealer',
    'users_collection': 'users',
}

### DATADEALER URLS & DJANGO-ALLAUTH SETTINGS

LOGIN_REDIRECT_URL='https://datadealer.local/#load' # redirect after login
ACCOUNT_LOGOUT_REDIRECT_URL = 'https://datadealer.local/' # redirect after logout
INVITATION_REQUIRED = False
INVITATION_FAILED = 'https://datadealer.local/#access_denied'

ACCOUNT_EMAIL_SUBJECT_PREFIX = "[My Data Dealer Dev Setup] "

ALLOWED_HOSTS = ['.datadealer.local']
SESSION_COOKIE_DOMAIN = ".datadealer.local"
