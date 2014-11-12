import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.md')).read()
CHANGES = open(os.path.join(here, 'CHANGES.txt')).read()

requires = [
    'pyramid==1.4',
    'gunicorn==18.0',
    'gevent'==1.0,
    'redis',
    'hiredis',
    'pymongo==2.6.3',
    'pyramid-beaker',
    'pyramid-rpc',
    'Django==1.4',
    'decorator',
    'celery==3.1.6',
    'pytz',
    'pyramid-exclog',
    'pyramid_sockjs',
    ]

setup(name='dd_app',
      version='0.2.0',
      description='dd_app',
      long_description=README + '\n\n' +  CHANGES,
      classifiers=[
        "Programming Language :: Python",
        "Framework :: Pyramid",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        ],
      author='Cuteacute Media OG',
      author_email='hq@cuteacute.com',
      url='',
      keywords='web pyramid pylons',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      tests_require=requires,
      test_suite="dd_app",
      entry_points = """\
      [paste.app_factory]
      main = dd_app:main
      """,
      )

