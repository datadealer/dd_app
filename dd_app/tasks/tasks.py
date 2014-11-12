from dd_app.tasks.cel import celery
from dd_app.messaging.mixins import MsgMixin

from pyramid.threadlocal import get_current_registry

class DDTask(celery.Task, MsgMixin):
    abstract = True
    ignore_result = True
    retry_policy = {'max_retries': 10,
                    'interval_start': 1,
                    'interval_step': 1,
                    'interval_max': 10}

    def _get_reg_settings(self):
        return get_current_registry().settings

    @property
    def redis(self):
        if not hasattr(self, '_redis'):
            self._redis = get_current_registry().settings['redis.connector']
        return self._redis

    @property
    def mongodb(self):
        if not hasattr(self, '_mongodb'):
            self._mongodb = get_current_registry().settings['mongodb.connector']
        return self._mongodb

    @property
    def logdb(self):
        if not hasattr(self, '_logdb'):
            self._logdb = get_current_registry().settings['logdb.connector']
        return self._logdb

    def get_user_info(self, auth_uid):
        if not hasattr(self, '_userdata'):
            self._userdata = {auth_uid: self.mongodb.get_user_by_auth_uid(auth_uid)}
        else:
            if getattr(self, '_userdata', {}).get(auth_uid, None) is None:
                self._userdata[auth_uid] = self.mongodb.get_user_by_auth_uid(auth_uid)
        return self._userdata.get(auth_uid, {})

    def game_base_query(self, auth_uid):
        # FIXME redundant mit base_handlers.DjangoSessionMixin (!!!)
        # fix dis shit
        userdata = self.get_user_info(auth_uid)
        oid = userdata['_id']
        query_base = {'user.$id': oid}
        version = userdata.get('game_version', None)
        if version is not None:
            query_base.update({'version': version})
        return query_base

    def _get_rules(self, version, lang='en'):
        if getattr(self, '_dd_rules', {}).get(version, {}).get(lang, None) is None:
            from dd_app.rules import RulesVersion
            if getattr(self, '_dd_rules', None) is None:
                self._dd_rules = {}
                if self._dd_rules.get(version, None) is None:
                    self._dd_rules[version] = {}
            self._dd_rules[version].update({lang: RulesVersion(version=version, lang=lang)})
        return self._dd_rules[version].get(lang)


@celery.task(base=DDTask)
def test(uid, x, y):
    result = x+y
    return result

@celery.task(base=DDTask)
def chargePerpReady(user_oid, auth_uid, node, start, result):
    # FIXME check for redundancies w. json-rpc handlers
    db = chargePerpReady.mongodb.get_db()
    query_find = {'nodes_charging.path': node['full_path']}
    query_find.update(chargePerpReady.game_base_query(auth_uid))
    resp = db.games.update(query_find,
                           {'$pull': {'nodes_charging': {'path': node['full_path']}},
                            '$push': {'nodes_collect': {'path': node['full_path'], 'result': result}}},
                           upsert=False,
                           multi=False)
    found = (resp.get('n', 0)>0)
    if found:
        chargePerpReady.dd_msg.node_ready(uid=auth_uid,
                                        node_type=node['game_type'],
                                        node_id=unicode(node['game_id']),
                                        path=node['full_path'],
                                        result=result)
    return 1

@celery.task(base=DDTask)
def notifyLevelupItems(auth_uid, version, lang, level, current_nodes=[]):
    rv = notifyLevelupItems._get_rules(version, lang)
    perps = rv.get_levelup_items(level)
    powerups = rv.get_levelup_powerups(level, current_nodes)
    if perps or powerups:
        notifyLevelupItems.dd_msg.notify_available(uid=auth_uid,
                                                           data={'perps': perps,
                                                                 'powerups': powerups,
                                                                 'trigger': 'levelup',
                                                                 'level': level
                                                                })
    return 1

@celery.task(base=DDTask)
def notifyBuyperpItems(auth_uid, version, lang, level, provider_gestalt, current_nodes=[]):
    rv = notifyLevelupItems._get_rules(version, lang)
    consumers = rv.get_new_consumers_for_provider(provider_gestalt, level=level, current_nodes=current_nodes)
    if consumers:
        notifyLevelupItems.dd_msg.notify_available(uid=auth_uid,
                                                   data={'perps': consumers.keys(),
                                                         'trigger': 'buy_provider',
                                                         'level': level,
                                                         'provider': provider_gestalt,
                                                        })
    return 1

@celery.task(base=DDTask)
def logAction(uid=0, action=None, time=None, **kwargs):
    try:
        db = logAction.logdb.get_db()
    except KeyError:
        return 1
    assert(action in ['newgame', 'loadgame', 'missiondone', 'levelup', 'charge', 'collect', 'integrate', 'buyperp', 'buypowerup', 'incident'])
    collection = db[action]
    collection.ensure_index('uid')
    collection.ensure_index('time')
    if action=='levelup':
        collection.ensure_index('level')
    if action=='missiondone':
        collection.ensure_index('mission')
    doc = {'uid': uid,
           'time': time}
    optional_args = ['level', 'xp', 'lang', 'mission', 'active_missions', 'game_values', 'target', 'costs', 'gain', 'project', 'karma', 'origins', 'karmalizer']
    for a in optional_args:
        val = kwargs.get(a, None)
        if val is not None:
            doc[a] = val
    collection.save(doc)
    return 1
