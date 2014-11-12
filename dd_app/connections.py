"""
Helper classes providing connection to external services/storage providers
"""

import pymongo
import redis
import datetime
from bson.dbref import DBRef

from dd_app.rules import RulesVersion


class MongoConnector(object):

    def __init__(self, uri, db):
        self._uri = uri
        self._db_name = db

    def get_connection(self):
        """Returns a pymongo connection"""
        return pymongo.mongo_client.MongoClient(host=self._uri, use_greenlets=True, tz_aware=True)

    def get_db(self):
        """Returns a pymongo.database.Database instance"""
        if not hasattr(self, '_db'):
            self._db = self.get_connection()[self._db_name]
        return self._db


class DDMongoConnector(MongoConnector):
    """MongoDB connector

    :param uri: mongodb URI

    :param db: mongodb database identifier

    :param users: name of collection containing userdata

    """

    def __init__(self, uri, db, users, *args, **kwargs):
        self._uri = uri
        self._db_name = db
        self._users_collection = users

    def get_user_by_auth_uid(self, uid, *args):
        """Fetch user by userid"""
        # TODO move me to pseudomodel layer?
        db = self.get_db()
        result = db[self._users_collection].find_one({'auth_uid': uid, 'auth_is_active': True}, *args)
        # db.connection.end_request()
        return result

    def create_game(self, oid):
        """ FIXME this is a test only """
        db = self.get_db()
        rules = RulesVersion(lang='en')
        rules.set_newgame()
        uref = DBRef(collection=self._users_collection, id=oid)
        game = rules.get_new_game()
        game['user'] = uref
        db['games'].ensure_index('user.$id')
        db['games'].ensure_index('version')
        db['games'].ensure_index([('user.$id', pymongo.ASCENDING), ('version', pymongo.DESCENDING)])
        db['games'].ensure_index('nodes.game_id')
        db['games'].ensure_index('nodes.full_path')
        db['games'].ensure_index([('nodes.instance_data.powerups.gestalt', pymongo.ASCENDING), ('nodes.instance_data.powerups.gestalt', pymongo.ASCENDING)])
        game['_id'] = db['games'].save(game, safe=True)
        db[self._users_collection].update({'_id': oid}, {'$set': {'game_version': game.get('version', None)}}, safe=True)
        # db.connection.end_request()
        return game

    def get_game(self, oid, version=None):
        """ FIXME this is a test only """
        query = {'user.$id':oid}
        created = False
        if version is not None:
            query.update({'version': version})
        db = self.get_db()
        result = db['games'].find_one(query)
        if result is None:
            result = self.create_game(oid)
            created = True
        # deref user ref
        u_deref = db.dereference(result['user'])
        result['user'] = u_deref
        result['server_time'] = datetime.datetime.utcnow()
        # db.connection.end_request()
        return result, created

    def drop_game(self, oid, version=None):
        query = {'user.$id':oid}
        if version is not None:
            query.update({'version': version})
        db = self.get_db()
        result = db['games'].remove(query)
        return result

    def get_top_values(self, value_field, num=50):
        db = self.get_db()
        db['games'].ensure_index([('game_values.%s' % value_field, pymongo.DESCENDING),])
        games = db['games'].find({}, {'game_values.%s' % value_field :1, '_id': 0, 'user': 1}).sort('game_values.%s' % value_field, pymongo.DESCENDING).limit(num)
        return [{'value': doc.get('game_values', {}).get(value_field, 0), 'user': doc['user'].id} for doc in games]

    def get_display_names_map(self, oids):
        db = self.get_db()
        users = db['users'].find({'_id': {'$in': oids}}, {'display_name': 1})
        result = dict((u['_id'], u.get('display_name', '')) for u in users)
        return result

    def get_rank(self, oid, value_field):
        db = self.get_db()
        query = {'user.$id': oid}
        db['games'].ensure_index([('game_values.%s' % value_field, pymongo.DESCENDING),])
        game = db['games'].find_one(query, {'game_values.%s' % value_field: 1})
        hasmore = db['games'].find({'game_values.%s' % value_field: {'$gt': game.get('game_values', {}).get(value_field, 0)}}).count()
        total = db['games'].count()
        if total==0:
            # no games, no nothing
            return 0
        rank = float((total - hasmore))/total
        return rank

    def get_game_version(self, uid):
        return self.get_user_by_auth_uid(uid, {'game_version': 1})


class DDRedisConnector(object):
    """Redis connector

    :param host: hostname/ip Redis is listening on

    :param port: port Redis is listening on

    :param db_num: Redis DB id

    """
    _redis = None
    _host = None
    _port = None
    _db_num = None

    def __init__(self, host, port, db_num, *args, **kwargs):
        self._host = host
        self._port = port
        self._db_num = db_num
        self._password = kwargs.get('password', None)

    def get(self):
        """Returns a redis connection from pool"""
        if self._redis is None:
            self._redis = redis.ConnectionPool(host=self._host, port=int(self._port), db=int(self._db_num), password=self._password)
        return redis.StrictRedis(connection_pool = self._redis)
