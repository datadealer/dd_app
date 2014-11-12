# dd_app #

A service providing a backend for [Data Dealer](https://datadealer.com)

## Copyright

Copyright (c) 2011-2014, Cuteacute Media OG
`dd_auth` is released under the Artistic License 2.0. See `LICENSE.txt`

## [Data Dealer](https://datadealer.com) stack requirements and a setup example ##

### Requirements

To deploy Data Dealer, you will need:

* python 2.7, python-virtualenv and python-pip
* libevent including development files
* a MongoDB instance to store game data
* a Redis database to back internal communications
* a Redis database to provide broker services for celery
* a Redis database to store session data shared between `dd_app` and `dd_auth`
* a Django-ORM compatible relational database storage. For testing purposes, a
sqlite database may suite your needs. Still, we strongly recommend to setup
a PostgreSQL or MySQL database for this purpose.
* a [dd_auth service](https://github.com/datadealer/dd_auth), configured according to your depolyment specifics
* recent Node.js and npm to build `dd_js` distribution
* a [dd_js](https://github.com/datadealer/dd_js) distribution build, configured according to your depolyment specifics
* a set of [dd_rules](https://github.com/datadealer/dd_rules) 
* a HTTP frontend to serve static files, reverse-proxy requests to `dd_app` and `dd_auth` HTTP services, `dd_app` websocket service,
and to provive SSL/TLS termination (recommended).
* an SMTP relay to enable email notifications

### Sample setup

We assume a deployment of Data Dealer as `https://datadealer.local`, using [nginx](http://nginx.org) as a HTTP frontend, 
use of [supervisor](http://supervisord.org/) to manage `dd_auth` and `dd_app` processes.

#### Setup databases

Install and setup a [Redis](http://redis.io/) and a [MongoDB](https://www.mongodb.org/) instance. See `examples/redis/` and `examples/mongodb`.

Install and setup PostgreSQL. Create a database `dd_auth` and user `dd_auth` to access it:

    $ createdb -E UTF8 dd_auth
    $ createuser -P
    [...]

grant permissions:

    $ psql
    # GRANT ALL PRIVILEGES ON DATABASE dd_auth TO dd_auth;

Create a user to run datadealer services. Run:

    $ sudo adduser --disabled-login --gecos 'datadealer dev env' dd

#### Prepare deployment

as user `dd`, create a directory setup and virtual environments, clone the repositories:

    $ mkdir ~/src
    $ mkdir ~/venv
    $ virtualenv --no-site-packages ~/venv/dd_app
    $ virtualenv --no-site-packages ~/venv/dd_auth
    $ cd ~/src
    $ git clone https://github.com/datadealer/dd_rules.git
    $ git clone https://github.com/datadealer/dd_auth.git
    $ git clone https://github.com/datadealer/dd_js.git
    $ git clone https://github.com/datadealer/dd_app.git

#### Build/setup applications

Use corresponding instructions to set up dd_auth, dd_app, dd_js and dd_rules. 

Set up supervisor and start the `dd_auth`, `dd_app` and `dd_app_sock` services.

Sample configuration files can be found at `examples/dd_app`, `examples/dd_auth` and `examples/dd_js.

#### Setup nginx

See sample configuration here: `examples/nginx/datadealer.local`. Remember to provide your own SSL certificate/key files.

## Setting up a dd_app development environment ##

### WARNING
 
Proceed with caution! `dd_app` can be only considered as a proof-of-concept. It may contain 
parts in dire need of a cleanup and rests of obsolete concepts and ideas. Some of its concepts 
should be reworked ASAP. There are no testsuites provided.

### Setup virtual environment ###

Create and activate a virtual environment (Python 2.7):

    $ virtualenv --no-site-packages /path/to/venv
    $ source /path/to/venv/bin/activate

Setup the application environment:

    $ python setup.py develop

### Configure application ###

Use `development.ini` as a template or use provided examples:

    $ cp development.ini local.ini

Edit `local.ini` according to your local setup.
You'd probably need to change following values:

* In section `[app:main]` - application configuration
    * `mongodb.uri` and `mongodb.db`
    * `redis.host`, `redis.port` and `redis.db`
    * `django.secret` - use the secret specified in settings of the
    dd_auth application used with this dd_app instance
* In section `[server:main]` - wsgi server configuration
    * set `host`, `port` and `workers` according to your needs

Create another configuration file `local_sock.ini` for the sockjs handler, see `examples/dd_app/local_sock.ini`

### Configure rulesets

Create a file `dd_app/rules/rulesets/settings_local.py` specifying a path to [dd_rules](https://github.com/datadealer/dd_auth) json files:

    RULEPATH = '/home/user/src/dd_rules'

### Configure celery ###

Use `dd_app/tasks/celeryconfig_template.py` as a template:

    $ cp dd_app/tasks/celeryconfig_template.py dd_app/tasks/celeryconfig.py

Edit `dd_app/tasks/celeryconfig.py` according to your local setup.
Specifically, check `BROKER_URL`, `CELERY_RESULT_BACKEND` and `DD_PYRAMID_INI` parameters.
Latter should point to exact path of pyramid ini file you intend to use.

### Start the application ###

Start celery worker:

    $ celery worker --config dd_app.tasks.celeryconfig

Start the application server:

    $ pserve local.ini
