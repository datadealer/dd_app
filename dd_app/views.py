"""Request handlers
"""

from pyramid.view import view_config
from pyramid.httpexceptions import HTTPForbidden

from pyramid_rpc.jsonrpc import jsonrpc_method
from bson.objectid import ObjectId

from dd_app.base_handler import BaseHandler, dd_protected
from dd_app.chargecollect import CollectablePerp
from dd_app.perps import PerpNode
from dd_app.missions import MissionHandler

import datetime, pytz, math, random

from dd_app.tasks import logAction

from dd_app import helpers

def millis_since_epoch():
    epoch = datetime.datetime.utcfromtimestamp(0)
    delta = datetime.datetime.utcnow() - epoch
    return int(math.ceil(delta.total_seconds()*1000))

class FakeHandler(BaseHandler):

    @view_config(route_name='home', renderer='string')
    def nope(self):
        """Uhm...?"""
        raise HTTPForbidden('my hovercraft is full of eels!')

class ApiHandler(BaseHandler):

    def _mergeTokens(self, original, new, minus=False):
        new_tokens_dict = dict((t['gestalt'], t) for t in new)
        old_tokens_dict = dict((t['gestalt'], t) for t in original)
        result = []
        for item in original:
            elem = {}
            gestalt = item['gestalt']
            elem.update(old_tokens_dict[gestalt])
            if gestalt in new_tokens_dict.keys():
                if minus:
                    elem['amount'] = max(elem['amount'] - new_tokens_dict[gestalt]['amount'], 0)
                else:
                    elem['amount'] = min(elem['amount'] + new_tokens_dict[gestalt]['amount'], 100)
            if elem['amount'] > 0:
                result.append(elem)
        if not minus:
            for item in new:
                elem = {}
                gestalt = item['gestalt']
                if gestalt not in old_tokens_dict.keys():
                    elem.update(new_tokens_dict[gestalt])
                    if elem['amount'] > 0:
                        result.append(elem)
        return result

    def _get_rules(self, version):
        if getattr(self, '_dd_rules', {}).get(version, None) is None:
            from dd_app.rules import RulesVersion
            if getattr(self, '_dd_rules', None) is None:
                self._dd_rules = {}
            self._dd_rules.update({version: RulesVersion(version=version, lang=self.session_language).rules})
        return self._dd_rules.get(version)

    def _get_level_for_xp(self, xp_value, version):
        rules = self._get_rules(version)
        levels = [l for l in rules.levels if xp_value>=l['xp_min'] and xp_value<=l['xp_max']]
        if len(levels) < 1:
            raise Exception('No levels for xp_value %s' % xp_value)
        return levels[0]

    def get_typedata_by_path(self, path, db=None, include_nodes=False, extra_query={}):
        query_base = self.game_query_base
        if db is None:
            db = self.mongo.get_db()
        query_find = {'nodes.full_path': path}
        query_find.update(query_base)
        query_find.update(extra_query)
        if include_nodes:
            db_result = db['games'].find_one(query_find, {'nodes': 1, 'version': 1, 'game_values': 1, 'nodes_lock': 1, 'mission_goals': 1, 'active_missions': 1})
            if db_result is not None:
                matched_nodes = [node for node in db_result['nodes'] if node['full_path']==path]
                node = matched_nodes[0]
                nodes = db_result['nodes']
        else:
            db_result = db['games'].find_one(query_find, {'nodes.$': 1, 'version': 1, 'game_values': 1, 'nodes_lock': 1, 'mission_goals': 1, 'active_missions': 1})
            if db_result is not None:
                nodes = []
                node = db_result['nodes'][0]
        if db_result is not None:
            version = db_result['version']
            game_values = db_result['game_values']
            gestalt = node['full_type'].split(':')[-1]
            rules = self._get_rules(version=version)
            perp = rules.perps.get(gestalt, rules.tokens.get(gestalt, {}))
            return perp['type_data'], node, game_values, rules, nodes, version, db_result
        return None

    def _get_gestalten_for_nodes(self, nodes=[]):
        return [node['full_type'].split(':')[-1] for node in nodes]

    def _deferred_levelup(self, level, version, nodes=[]):
        from dd_app.tasks import notifyLevelupItems
        notifyLevelupItems.apply_async(kwargs = {
                                                    'auth_uid': self.auth_uid,
                                                    'version': version,
                                                    'lang': self.session_language,
                                                    'level': level,
                                                    'current_nodes': self._get_gestalten_for_nodes(nodes),
                                                },
                                       countdown=2)

    def _deferred_buyperp(self, level, version, provider_gestalt, nodes=[]):
        if provider_gestalt.startswith('project') or provider_gestalt.startswith('contact'):
            from dd_app.tasks import notifyBuyperpItems
            notifyBuyperpItems.apply_async(kwargs={
                                                    'auth_uid': self.auth_uid,
                                                    'version': version,
                                                    'lang': self.session_language,
                                                    'level': level,
                                                    'provider_gestalt': provider_gestalt,
                                                    'current_nodes': self._get_gestalten_for_nodes(nodes),
                                                  },
                                           countdown=2)

    def _handle_levelup(self, new_xp, old_xp, version):
        levelinfo = self._get_level_for_xp(old_xp, version)
        levelup = False
        query_inc = {}
        query_set = {}
        next_levelinfo = levelinfo
        if new_xp > levelinfo['xp_max']:
            levelup = True
            next_levelinfo = self._get_level_for_xp(new_xp, version)
            query_inc['game_values.xp_level'] = next_levelinfo['number'] - levelinfo['number']
            query_set['game_values.ap_snapshot'] = next_levelinfo['ap_max']
            query_set['game_values.ap_update'] = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
        return levelup, query_inc, query_set, next_levelinfo

    @jsonrpc_method(endpoint='api')
    def getToken(self):
        """Fetch auth token

        :returns: token according to cookie set by auth service
        :rtype: json string

        If calling client sends a proper session cookie, that can be validated
        as representing a valid authenticated session for a valid user, it
        returns a token string which can be used to authenticate calls to
        protected methods.

        If validation fails, returns
        :py:class:`dd_api.jsonrpc.JsonRpcUnauthorized` error
        """
        if not self.check_user():
            raise HTTPForbidden('unauthorized')
        return self.get_session_cookie()

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def userData(self, token):
        """Fetch user data

        :param token: string containing token as acquired by
                      :py:func:`getToken`
        :type token: string
        :returns: user data
        :rtype: json object

        .. todo:: See *USER_SCHEMA_DOC_MISSING*

        For a valid auth-token retrieve a json object with user data of the
        user the token is authentificated for.
        """
        return self.get_user_info()

    @jsonrpc_method(endpoint='api')
    def getSessionLocale(self):
        return self.session_language

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def resetGame(self, token):
        oid = self.userdata['_id']
        version = self.userdata.get('game_version', None)
        return self.mongo.drop_game(oid, version=version)


    @dd_protected
    @jsonrpc_method(endpoint='api')
    def loadGame(self, token, extra_types=True):
        """Fetch game data

        :param token: string containing token as acquired by
                      :py:func:`getToken`
        :type token: string
        :returns: game data
        :rtype: json object

        .. todo:: See **GAME_SCHEMA_DOC_MISSING** **TODO** for details.

        For a valid auth-token retrieve a json object with game data (version
        according to ``user.game_version``) of the user the token is authentificated for.

        .. note:: User ``DBRef()`` of the game object is fully dereferenced.
        """
        oid = self.userdata['_id']
        version = self.userdata.get('game_version', None)
        game,created = self.mongo.get_game(oid, version=version)
        if created:
            logAction.apply_async(kwargs={
                'action': 'newgame',
                'uid': self.auth_uid,
                'time': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC),
                'lang': self.session_language,
                'xp': 0,
            })
        gid = unicode(game['_id'])
        game['_id'] = gid
        if version is None:
            version = game.get('version')
        rules = self._get_rules(version=version)
        levelinfo = self._get_level_for_xp(game.get('game_values').get('xp_value'), version)
        ap_initial, ap_up = helpers.calculateAP(game['game_values']['ap_snapshot'],
                                                game['game_values']['ap_update'],
                                                levelinfo)
        game['game_values']['ap_initial'] = ap_initial
        ap_delta = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC) - ap_up
        game['game_values']['ap_offset'] = int(ap_delta.total_seconds()*1000)
        if extra_types:
            tr = {}
            tr.update(rules.tokens)
            tr.update(rules.perps)
            game['type_registry'] = tr
            game['levels'] = rules.levels
            game['karmalauters'] = rules.karmalauters
            game['karmalizers'] = rules.karmalizers
            game['missions'] = rules.missions
            game['is_new_game'] = created

        if not created:
            logAction.apply_async(kwargs={
                'action': 'loadgame',
                'uid': self.auth_uid,
                'time': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC),
                'lang': self.session_language,
                'level': game['game_values'].get('xp_level', 0),
                'xp': game['game_values'].get('xp_value', 0),
            })
        return game

    def _log_mission_complete(self, mission, game_values):
        logAction.apply_async(kwargs={
            'action': 'missiondone',
            'uid': self.auth_uid,
            'time': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC),
            'level': game_values['xp_level'],
            'xp': game_values['xp_value'],
            'mission': mission,
        })

    def _log_levelup(self, active_missions, game_values):
        logAction.apply_async(kwargs={
            'action': 'levelup',
            'uid': self.auth_uid,
            'time': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC),
            'level': game_values['xp_level'],
            'active_missions': active_missions,
            'game_values': game_values,
            'xp': game_values['xp_value'],
        })

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def setPerpCoordinates(self, token, updates):
        """
        :param token: string containing token as acquired by
                      :py:func:`getToken`
        :param updates: list containing ``[path, position]`` pairs, where
                        ``path`` is a string containing the dot-separated
                        tree path of the updated object, for example
                        ``"Imperium.CityVienna.Agent0.Contact3"``.
                        ``position`` is a coordinates object with ``x`` and
                        ``y`` coordinates, example: ``{"x": 30, "y": 666}``
        :returns: number of updated documents
        :rtype: json int

        Updates position of a game node described by ``path`` in game document
        of ``user.game_version`` version of user the ``token`` is authenticated
        for, setting them to ``position``.

        .. todo:: Cleanup & organize

        """
        query_base = self.game_query_base
        db = self.mongo.get_db()
        updated = 0
        for path, position in updates:
            query_find = {}
            query_set = {}
            x, y = (position.get('x', None), position.get('y', None))
            # TODO in eine query verpacken moeglich?
            if (path is not None) and (x is not None or y is not None):
                container = 'nodes'
                query_find.update({'%s.full_path' % container: path})
                query_find.update(query_base)
                if x is not None:
                    query_set.update({'%s.$.instance_data.x' % container: int(x)})
                if y is not None:
                    query_set.update({'%s.$.instance_data.y' %container: int(y)})
            resp = db['games'].update(query_find, {'$set': query_set}, safe=True, upsert=False, multi=False)
            updated += resp.get('n', 0)
        return updated

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def integrateCollected(self, token, collect_id):
        """
        WIP
        """
        NOT_IN_QUEUE = 0
        NOT_ENOUGH_AP = 1
        BUBU = 2 # lock or ap second-check failed, should not happen
        now_ms = millis_since_epoch()
        xp_increment = 1
        ap_cost = 1
        # find: find game, read Token nodes, read profileset from queue, read version
        query_base = self.game_query_base
        db = self.mongo.get_db()
        query_find = {'db_queue.collect_id': collect_id}
        query_find.update(query_base)
        orig_data = db['games'].find_one(query_find, {'nodes': 1, 'db_queue.$': 1, 'version': 1, 'nodes_lock': 1, 'game_values': 1, 'mission_goals': 1, 'active_missions': 1})
        if orig_data is None:
            return {'error': NOT_IN_QUEUE}
        # collect all tokes types, set amounts, merge
        game_values = orig_data['game_values']
        queue_data = orig_data['db_queue'][0]
        nodes = orig_data.get('nodes', [])
        version = orig_data.get('version', 1)
        rules = self._get_rules(version=version)
        levelinfo = self._get_level_for_xp(game_values['xp_value'], version)
        ap_base_dt = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
        ap_current, ap_up = helpers.calculateAP(game_values['ap_snapshot'],
                                                game_values['ap_update'],
                                                levelinfo,
                                                datenow=ap_base_dt)
        if ap_current < ap_cost:
            return {'error': NOT_ENOUGH_AP}

        db_nodes = dict((n['gestalt'], n.get('instance_data', {}).get('amount', 0))
                        for n in nodes
                        if n.get('game_type', None)=='TokenPerp')
        token_amounts = dict((item, 0) for item in rules.tokens.keys())
        token_amounts.update(db_nodes)
        db_args = {'db_map': [{'type': k, 'amount': v} for k, v in token_amounts.items()],
                   'db_amount': game_values['profiles_value'],
                   'db_max': game_values['profiles_max']}
        profileset = queue_data.get('profile_set', {})
        profileset_args = {
            'profileset_amount': profileset.get('profiles_value'),
            'profileset_map': [{'type': k, 'amount': v.get('amount', 0)} for k, v in profileset.get('tokens_map').items()]
        }
        db_args.update(profileset_args)
        from dd_app.dd_merger import Merger
        merger = Merger(db_args)
        merged = merger.merge()
        #return merged, db_args['db_map']
        # find new tokes, generate node elements
        old_tokens = db_nodes.keys()
        modified_tokens = [elem['type'] for elem in merged['mapping']]
        new_vals = dict((e['type'], e['amount']) for e in merged['mapping'])
        mh = MissionHandler(version,
                            self.session_language,
                            goal_data=orig_data.get('mission_goals', []),
                            active_missions=orig_data.get('active_missions', []),
                            game_nodes=nodes,
                            db=db,
                            game_id=orig_data['_id'],
                            game_values=game_values)
        goals_met = False
        response_extra = {}
        for gestalt in [t for t in modified_tokens if t not in old_tokens]:
            if gestalt not in old_tokens:
                elem = {}
                elem_id = unicode(ObjectId())
                elem['game_type'] = 'TokenPerp'
                elem['full_type'] = 'TokenPerp:%s' % gestalt
                elem['game_id'] = elem_id
                elem['gestalt'] = gestalt
                elem['full_path'] = 'Database.%s' % elem_id
                elem['instance_data'] = {}
                nodes.append(elem)
        for node in nodes:
            if node.get('gestalt', None) in modified_tokens:
                mh.set_new_amount(int(merged.get('amount')))
                goals_met = goals_met or mh.handle_integrateprofiles(node['gestalt'], new_vals[node['gestalt']])
                node['instance_data'].update({'amount': new_vals[node['gestalt']]})
        rewards = mh.compute_rewards()
        # find_and_modify: find game w. correct version, if none -> abort, remove profileset from queue, write new node elements and update others
        query_set = {
            '$pull': {'db_queue': {'collect_id': collect_id}},
            '$inc': {
                     'game_values.xp_value': xp_increment + rewards.get('xp_value', 0),
                     'game_values.cash_value': rewards.get('cash_value', 0),
                     'game_values.karma_value': min(rewards.get('karma_value', 0), 100-game_values['karma_value']),
                     'nodes_lock': 1,
                    },
            '$set': {'nodes': nodes,
                     'game_values.profiles_value': int(merged.get('amount'))},
            '$push': {},
        }
        if goals_met:
            new_mission_data = {'mission_goals': mh.get_goals(),
                                'active_missions': mh.active_missions}
            query_set['$set'].update(new_mission_data)
            response_extra.update({'missions': {'complete_missions': mh.complete_missions,
                                                'updated_missions': mh.updated_missions,
                                                'mission_data': new_mission_data,
                                                'rewards': rewards}})
            profile_sets = rewards.get('profile_sets', [])
            for m in mh.complete_missions:
                self._log_mission_complete(m, game_values)
            if len(profile_sets)>0:
                query_set['$push'].update({'db_queue': {'$each': profile_sets}})
        new_xp = game_values['xp_value'] + xp_increment + rewards.get('xp_value', 0)
        # levelup
        levelup, inc_update, set_update, next_levelinfo = self._handle_levelup(new_xp, game_values['xp_value'], version)
        query_set['$inc'].update(inc_update)
        query_set['$set'].update(set_update)
        if not levelup:
            query_set['$set']['game_values.ap_snapshot'] = ap_current-ap_cost
            query_set['$set']['game_values.ap_update'] = ap_up
        query_find = {}
        query_find.update(query_base)
        if orig_data.get('nodes_lock', None) is None:
            query_find.update({'nodes_lock': {'$exists': False}})
        else:
            query_find.update({'nodes_lock': orig_data['nodes_lock']})
        query_find.update({
                             '$where': 'function() { return Math.min(this.game_values.ap_snapshot + (parseInt((%s-this.game_values.ap_update.getTime()) / %s)) * %s, %s) >= %s; }' % (now_ms, levelinfo['ap_inc_interval'], levelinfo['ap_inc_value'], levelinfo['ap_max'], ap_cost),
                         })
        resp = db['games'].find_and_modify(query=query_find,
                                           update=query_set,
                                           upsert=False,
                                           new=True,
                                           fields={'game_values': 1, 'nodes': 1})
        if resp is None:
            return {'error': BUBU}
        # return results
        result_nodes = [n for n in resp['nodes'] if n.get('game_type', None)=='TokenPerp']
        response = {'result': {'nodes': result_nodes,
                               'increment': int(merged.get('increment')),
                               'dup': int(merged.get('dup'))},
                    'game_values': resp['game_values']}
        response['game_values'].update({'ap_increment': -ap_cost})
        response.update(response_extra)
        if levelup:
            response.update({'levelup': levelup})
            response['game_values'].update({'ap_initial': next_levelinfo['ap_max']})
            self._deferred_levelup(level=response['game_values']['xp_level'], version=version, nodes=resp['nodes'])
            self._log_levelup(orig_data.get('active_missions', []), game_values)
        logAction.apply_async(kwargs={
            'action': 'integrate',
            'uid': self.auth_uid,
            'time': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC),
            'level': game_values['xp_level'],
            'xp': game_values['xp_value'],
            'origins': [k for k in profileset.get('tokens_map', {}).keys() if k.startswith('origin')],
        })
        return response

    def _handleKarmaIncident(self, karma_value, version, level, xp):
        INCIDENT_THRESHOLD = 0
        KARMA_LIMIT = 100
        PROBABILITY_PADDING = 0.05
        CURVE_POWER = 0.5 # >0! >1 schnell steigend, <1 langsam
        if karma_value < INCIDENT_THRESHOLD:
            factor = pow((float(INCIDENT_THRESHOLD - karma_value)/-(-KARMA_LIMIT - INCIDENT_THRESHOLD)), CURVE_POWER)
            choices = {1: factor, 0: (1-factor)+PROBABILITY_PADDING}
            wr = helpers.WeightedRandomizer(choices)
            if wr.random() > 0:
                # select an incident
                rules = self._get_rules(version=version)
                karma_choice = [k for k in rules.karmalizers if level>=k.get('type_data', {}).get('required_level', 0)]
                if len(karma_choice)>0:
                    karmalizer = random.choice(karma_choice)
                    logAction.apply_async(kwargs={
                        'action': 'incident',
                        'uid': self.auth_uid,
                        'time': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC),
                        'level': level,
                        'xp': xp,
                        'karma': karma_value,
                        'karmalizer': karmalizer.get('type_data', {}).get('gestalt').split(':')[-1]
                    })

                    return karmalizer
        return None

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def collectPerp(self, token, path):
        """
        Proof-of-concept testing!!!

        :param token: string containing token as acquired by
                      :py:func:`getToken`
        :param path: string containing the the dot-separated
                     tree path of the charged contact
        :returns: duration of charge cycle in milliseconds if
                  charge start successful, else -1
        :rtype: json int
        """
        NOT_ENOUGH_AP = 2
        NOT_COLLECTABLE = 1
        BUBU = 3
        query_base = self.game_query_base
        db = self.mongo.get_db()

        def get_data(path, extra_query={}):
            q_find = {'nodes.full_path': path}
            q_find.update(query_base)
            q_find.update(extra_query)
            db_result = db['games'].find_one(q_find, {'nodes.$': 1, 'version': 1, 'game_values': 1, 'nodes_collect': 1, 'nodes_lock': 1, 'mission_goals': 1, 'active_missions': 1})
            if db_result is not None:
                node = db_result['nodes'][0]
                version = db_result['version']
                game_values = db_result['game_values']
                nodes_lock = db_result.get('nodes_lock', None)
                gestalt = node['full_type'].split(':')[-1]
                rules = self._get_rules(version=version)
                collectables = db_result.get('nodes_collect', [])
                result = [collect.get('result', None) for collect in collectables if collect.get('path')==path].pop()
                try:
                    prp = rules.perps[gestalt]
                except KeyError:
                    prp = rules.tokens[gestalt]
                return prp['type_data'], node, game_values, rules, result, version, nodes_lock, db_result.get('mission_goals', []), db_result.get('active_missions', []), db_result['_id']
            return None

        now_ms = millis_since_epoch()
        extra_query_find = {
            'nodes_collect.path': path,
            'nodes_charging.path': {'$ne': path}
        }
        old_game_data = get_data(path, extra_query=extra_query_find)
        if old_game_data is None:
            # Nothing to collect
            return {'error': NOT_COLLECTABLE}
        node_type_data, node_data, old_game_values, rules, result, version, nodes_lock, mission_goals, active_missions, game_id = old_game_data
        levelinfo = self._get_level_for_xp(old_game_values['xp_value'], version)
        ap_base_dt = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
        ap_current, ap_up = helpers.calculateAP(old_game_values['ap_snapshot'],
                                                old_game_values['ap_update'],
                                                levelinfo,
                                                datenow=ap_base_dt)
        ap_cost = node_type_data.get('collect_AP_cost', 1)
        xp_increment = node_type_data.get('xp_inc', 1)
        if ap_current < ap_cost:
            return {'error': NOT_ENOUGH_AP}

        collectable_cash = result.get('collect_cash', None)
        collectable_profileset = result.get('tokens_map', None)
        collectable_tokenamount = result.get('collect_tokenamount', None)
        collect_risk = result.get('collect_risk', 0)
        old_karma = old_game_values['karma_value']
        query_set = {
            '$pull': {'nodes_collect': {'path': path}},
            '$inc': {
                     'game_values.xp_value': xp_increment,
                     'nodes_lock': 1,
                    },
            '$set': {},
            '$push': {},
        }
        response = {}
        response_extra = {}
        mh = MissionHandler(version,
                            self.session_language,
                            goal_data=mission_goals,
                            active_missions=active_missions,
                            db=db,
                            game_id=game_id,
                            game_values=old_game_values)
        goals_met = False
        rewards = {}
        karma_i = 0
        xp_i = 0
        cash_i = 0
        if collectable_profileset is not None:
            queue_ps = {'origin': path,
                        'collect_id': unicode(ObjectId()),
                        'profile_set': result,
                        'collect_dt': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)}

            query_set.update({'$push': {'db_queue': queue_ps}})
            resp_result = queue_ps
            goals_met = goals_met or mh.handle_collectamount(node_data['full_type'].split(':')[-1], result['profiles_value'], 'collect_profiles')
            #goals_met = goals_met or mh.handle_integrateprofiles(node_data['full_type'].split(':')[-1], node_data.get('instance_data', {}).get('amount', 0))
        if collectable_cash is not None:
            query_set['$inc'].update({'game_values.cash_value': collectable_cash})
            resp_result = {'cash': collectable_cash}
            goals_met = goals_met or mh.handle_collectamount(node_data['full_type'].split(':')[-1], collectable_cash, 'collect_cash')
        if collectable_tokenamount is not None:
            old_profiles_value = result.get('last_upgrade_data').get('profiles_value')
            if old_profiles_value > 0:
                correction_factor = float(old_game_values['profiles_value'])/old_profiles_value
            else:
                # should never happen!
                correction_factor = 1
            tofull = 100 - node_data.get('instance_data', {}).get('amount', 0)
            increment = collectable_tokenamount.get(node_data['gestalt'])
            increment_corrected = increment/correction_factor
            if tofull<increment_corrected:
                increment_corrected = tofull
            query_set['$inc']['nodes.$.instance_data.amount'] = increment_corrected
            #query_set['$set']['nodes.$.instance_data.amount'] = node_data.get('instance_data', {}).get('amount', 0) + increment_corrected
            resp_result = {'token_upgraded_amount': node_data.get('instance_data', {}).get('amount', 0) + increment_corrected}
            goals_met = goals_met or mh.handle_upgradetoken(node_data['full_type'].split(':')[-1])
            goals_met = goals_met or mh.handle_integrateprofiles(node_data['full_type'].split(':')[-1], node_data.get('instance_data', {}).get('amount', 0) + increment_corrected)
        if goals_met:
            rewards = mh.compute_rewards()
            new_mission_data = {'mission_goals': mh.get_goals(),
                                'active_missions': mh.active_missions}
            profile_sets = rewards.get('profile_sets', [])
            if len(profile_sets)>0:
                query_set['$push'].update({'db_queue': {'$each': profile_sets}})
            query_set['$set'].update(new_mission_data)
            if collectable_cash is None:
                cash_i = rewards.get('cash_value', 0)
            else:
                cash_i = collectable_cash + rewards.get('cash_value', 0)
            xp_i = xp_increment + rewards.get('xp_value', 0)
            query_set['$inc'].update({'game_values.xp_value': xp_i})
            query_set['$inc'].update({'game_values.cash_value': cash_i})
            karma_i = rewards.get('karma_value', 0)
            #response_extra.update({'profile_set': profile_sets,})
            for m in mh.complete_missions:
                self._log_mission_complete(m, old_game_values)
            response_extra.update({'missions': {'complete_missions': mh.complete_missions,
                                                'updated_missions': mh.updated_missions,
                                                'mission_data': new_mission_data,
                                                'rewards': rewards}})

        if collect_risk is not None:
            if old_karma>-100:
                karma_rest = 100 + old_karma
                if collect_risk < karma_rest:
                    decrement = collect_risk + karma_i
                else:
                    decrement = karma_rest
            else:
                decrement = 0
            if node_data.get('game_type', '')!='ClientPerp':
                karmalizer = self._handleKarmaIncident(old_karma-decrement, version, old_game_values['xp_level'], old_game_values['xp_value'])
            else:
                karmalizer = None
            incident_extra = 0
            if karmalizer is not None:
                incident_extra = karmalizer.get('type_data', {}).get('karma_points', -1)
                response.update({'karma_incident': karmalizer.get('type_data', {}).get('gestalt')})
            if old_karma-decrement+incident_extra<=-100:
                query_set['$set'].update({'game_values.karma_value': -100})
            else:
                query_set['$inc'].update({'game_values.karma_value': -decrement+incident_extra+karma_i})
        new_xp = old_game_values['xp_value'] + xp_increment + rewards.get('xp_value', 0)
        # levelup
        levelup, inc_update, set_update, next_levelinfo = self._handle_levelup(new_xp, old_game_values['xp_value'], version)
        query_set['$inc'].update(inc_update)
        query_set['$set'].update(set_update)
        if not levelup:
            query_set['$set']['game_values.ap_snapshot'] = ap_current-ap_cost
            query_set['$set']['game_values.ap_update'] = ap_up
        query_find = {'nodes.full_path': path}
        query_find.update(query_base)
        if nodes_lock is None:
            query_find.update({'nodes_lock': {'$exists': False}})
        else:
            query_find.update({'nodes_lock': nodes_lock})
        query_find.update({
                             '$where': 'function() { return Math.min(this.game_values.ap_snapshot + (parseInt((%s-this.game_values.ap_update.getTime()) / %s)) * %s, %s) >= %s; }' % (now_ms, levelinfo['ap_inc_interval'], levelinfo['ap_inc_value'], levelinfo['ap_max'], node_type_data.get('collect_AP_cost', 1)),
                         })
        resp = db['games'].find_and_modify(query=query_find,
                                           update=query_set,
                                           upsert=False,
                                           new=True,
                                           fields={'game_values': 1, 'nodes': 1})
        if resp is None:
            return {'error': BUBU}
        response.update({'result': resp_result, 'game_values': resp['game_values']})
        response['game_values'].update({'ap_increment': -ap_cost})
        response.update(response_extra)
        if levelup:
            response.update({'levelup': levelup})
            response['game_values'].update({'ap_initial': next_levelinfo['ap_max']})
            self._deferred_levelup(level=response['game_values']['xp_level'], version=version, nodes=resp['nodes'])
            self._log_levelup(active_missions, old_game_values) # WARNING! no node data provided. gotta live with it
        logAction.apply_async(kwargs={
            'action': 'collect',
            'uid': self.auth_uid,
            'time': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC),
            'level': old_game_values['xp_level'],
            'xp': old_game_values['xp_value'],
            'target': node_data['full_type'].split(':')[-1],
            'gains': resp_result,
        })
        return response

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def chargePerp(self, token, path):
        """
        Proof-of-concept testing!!!

        :param token: string containing token as acquired by
                      :py:func:`getToken`
        :param path: string containing the the dot-separated
                     tree path of the charged contact
        :returns: duration of charge cycle in milliseconds if
                  charge start successful, else -1
        :rtype: json int

        .. todo:: UPDATE DOCUMENTATION!
        """
        NOT_ENOUGH_AP = 2
        xp_increment = 1
        query_base = self.game_query_base
        db = self.mongo.get_db()
        # we need all nodes to get db values for client charge/collect cycle
        node_type_data, node_data, old_game_values, rules, nodes, version, db_result = self.get_typedata_by_path(path, include_nodes=True)
        # kosten ermitteln
        cperp = CollectablePerp(node_type_data, node_data, rules, old_game_values, nodes=nodes)
        charge_result, charge_cost = cperp.getPerpChargeData()
        # levelinfo
        levelinfo = self._get_level_for_xp(old_game_values['xp_value'], version)
        # check if we are allowed to charge
        cost_cash = charge_cost.get('cash', 0)
        cost_ap = charge_cost.get('ap', 0)
        query_find = {'nodes.full_path': path,
                      'nodes_charging.path': {'$nin': [path]},
                      'nodes_collect.path': {'$nin': [path]},
                     }
        now_ms = millis_since_epoch()
        if cost_cash>0:
            query_find.update({'game_values.cash_value': {'$gte': cost_cash}})
        if cost_ap>0:
            ap_base_dt = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
            ap_current, ap_up = helpers.calculateAP(old_game_values['ap_snapshot'],
                                                    old_game_values['ap_update'],
                                                    levelinfo,
                                                    datenow=ap_base_dt)
            if ap_current < cost_ap:
                return {'error': NOT_ENOUGH_AP}
        query_find.update(query_base)
        mh = MissionHandler(version,
                            self.session_language,
                            goal_data=db_result.get('mission_goals', []),
                            active_missions=db_result.get('active_missions', []),
                            game_nodes=nodes,
                            db=db,
                            game_id=db_result.get('_id'),
                            game_values=old_game_values)
        goals_met = False
        rewards = {}
        goals_met = mh.handle_chargeperp(node_data['full_type'].split(':')[-1])
        rewards = mh.compute_rewards()
        response_extra = {}
        dt_base = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
        duration = node_type_data['charge_time']/self.debug_charge_accel
        eta = dt_base + datetime.timedelta(milliseconds=duration)
        query_set = {'$set': {'nodes.$.instance_data.charge_start': dt_base},
                     '$addToSet': {'nodes_charging': {'path': path, 'result': charge_result, 'charge_start': dt_base, 'charge_end': eta}},
                     '$inc': {'game_values.xp_value': xp_increment + rewards.get('xp_value', 0),
                              'nodes_lock': 1},
                     '$push': {},
                    }
        if goals_met:
            new_mission_data = {'mission_goals': mh.get_goals(),
                                'active_missions': mh.active_missions}
            query_set['$set'].update(new_mission_data)
            response_extra.update({'missions': {'complete_missions': mh.complete_missions,
                                                'updated_missions': mh.updated_missions,
                                                'mission_data': new_mission_data,
                                                'rewards': rewards}})
            for m in mh.complete_missions:
                self._log_mission_complete(m, old_game_values)
            profile_sets = rewards.get('profile_sets', [])
            if len(profile_sets)>0:
                query_set['$push'].update({'db_queue': {'$each': profile_sets}})
            query_set['$inc']['game_values.cash_value'] = rewards.get('cash_value', 0)

        upgrade_data = charge_result.get('last_upgrade_data', None)
        if db_result.get('nodes_lock', None) is None:
            query_find.update({'nodes_lock': {'$exists': False}})
        else:
            query_find.update({'nodes_lock': db_result['nodes_lock']})
        if upgrade_data is not None:
            query_set['$set']['nodes.$.instance_data.last_upgrade_values'] = upgrade_data
        if cost_cash>0:
            query_set['$inc'].update({'game_values.cash_value': -cost_cash + rewards.get('cash_value', 0)})
            query_set['$inc'].update({'game_values.cash_spent': cost_cash})
        if cost_ap>0:
            query_find.update({
                             '$where': 'function() { return Math.min(this.game_values.ap_snapshot + (parseInt((%s-this.game_values.ap_update.getTime()) / %s)) * %s, %s) >= %s; }' % (now_ms, levelinfo['ap_inc_interval'], levelinfo['ap_inc_value'], levelinfo['ap_max'], cost_ap),
                             })
            query_set['$set']['game_values.ap_snapshot'] = ap_current-cost_ap
            query_set['$set']['game_values.ap_update'] = ap_up
        levelup = False
        new_xp = old_game_values['xp_value'] + xp_increment + rewards.get('xp_value', 0)
        # levelup
        levelup, inc_update, set_update, next_levelinfo = self._handle_levelup(new_xp, old_game_values['xp_value'], version)
        query_set['$inc'].update(inc_update)
        query_set['$set'].update(set_update)
        if levelup:
            response_extra['levelup'] = True
        # TODO aufpassen! find_and_modify query muss sharding key enthalten!!!
        resp = db['games'].find_and_modify(query=query_find,
                                           update=query_set,
                                           upsert=False,
                                           fields={'game_values': 1},
                                           new=True)
        updated = (resp is not None)
        response = {}
        if updated:
            if levelup:
                self._deferred_levelup(level=resp['game_values']['xp_level'], version=version, nodes=nodes)
                self._log_levelup(db_result.get('active_missions', []), old_game_values)
            from dd_app.tasks import chargePerpReady
            chargePerpReady.apply_async(kwargs={
                                                   'user_oid': self.userdata['_id'],
                                                   'auth_uid': self.auth_uid,
                                                   'node': node_data, # safe to pass outdated data
                                                   'start': dt_base,
                                                   'result': charge_result,
                                                  },
                                           eta=eta)
            response.update(resp)
            del response['_id']
            response['duration'] = duration
            if cost_ap>0:
                response['game_values'].update({'ap_increment': -cost_ap})
            response.update(response_extra)
            logAction.apply_async(kwargs={
                'action': 'charge',
                'uid': self.auth_uid,
                'time': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC),
                'target': node_data['full_type'].split(':')[-1],
                'level': old_game_values['xp_level'],
                'xp': old_game_values['xp_value'],
                'costs': charge_cost,
            })
            return response
        return {'error': 1}

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def buySlots(self, token, perp_full_path, slot_type, slots):
        NOT_FOUND = 0
        INVALID_SLOT_TYPE = 1
        SLOTS_OVER_MAX = 2
        NOT_ENOUGH_CASH = 3
        BUBU = 4
        slots = int(slots)
        #xp_increment = int(slots)
        xp_increment = 0
        if slot_type not in self.powerup_types:
            return {'error': INVALID_SLOT_TYPE}
        query_base = self.game_query_base
        db = self.mongo.get_db()
        query_find = {'nodes.full_path': perp_full_path}
        query_find.update(query_base)
        orig_data = db['games'].find_one(query_find, {'nodes.$': 1, 'version': 1, 'nodes_lock': 1, 'game_values': 1, 'active_missions': 1})
        if orig_data is None:
            return {'error': NOT_FOUND}
        game_values = orig_data['game_values']
        active_missions = orig_data.get('active_missions', [])
        node_data = orig_data['nodes'][0]
        version = orig_data.get('version', 1)
        rules = self._get_rules(version=version)
        perp_gestalt = node_data['full_type'].split(':')[-1]
        project_typedata = rules.perps[perp_gestalt]['type_data']
        slots_key = '%s_slots' % slot_type
        max_slots_key = 'max_%s_slots' % slot_type
        current_slots = node_data.get('instance_data', {}).get(slots_key, project_typedata.get(slots_key, 0))
        max_slots = node_data.get('instance_data', {}).get(max_slots_key, project_typedata.get(max_slots_key, 0))
        if current_slots + slots > max_slots:
            return {'error': SLOTS_OVER_MAX}
        slot_cost = node_data.get('instance_data', {}).get('slot_cost', project_typedata.get('slot_cost', 0))
        price = slot_cost * slots
        if game_values['cash_value'] < price:
            return {'error': NOT_ENOUGH_CASH}
        query_set = {
            '$set': {
                        'nodes.$.instance_data.%s' % slots_key: current_slots + slots,
                    },
            '$inc': {
                        'game_values.xp_value': xp_increment,
                        'nodes_lock': 1,
                        'game_values.cash_value': -price,
                        'game_values.cash_spent': price,
                    },
                    }
        levelup = False
        new_xp = game_values['xp_value'] + xp_increment
        # levelup
        levelup, inc_update, set_update, next_levelinfo = self._handle_levelup(new_xp, game_values['xp_value'], version)
        query_set['$inc'].update(inc_update)
        query_set['$set'].update(set_update)

        query_find = {'nodes.full_path': perp_full_path,
                      'game_values.cash_value': {'$gte': price}}
        query_find.update(query_base)
        if orig_data.get('nodes_lock', None) is None:
            query_find.update({'nodes_lock': {'$exists': False}})
        else:
            query_find.update({'nodes_lock': orig_data['nodes_lock']})
        resp = db['games'].find_and_modify(query=query_find,
                                           update=query_set,
                                           upsert=False,
                                           new=True,
                                           fields={'game_values': 1, 'nodes': 1})
        if resp is None:
            return {'error': BUBU}
        node_data['instance_data'].update({slots_key: current_slots + slots})
        response = {'node': node_data,
                    'game_values': resp['game_values']}
        if levelup:
            response.update({'levelup': levelup})
            response['game_values'].update({'ap_initial': next_levelinfo['ap_max']})
            self._deferred_levelup(level=response['game_values']['xp_level'], version=version, nodes=resp['nodes'])
            self._log_levelup(active_missions, game_values)
        return response

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def buyKarma(self, token, karmalauter):
        NOT_FOUND = 1
        KARMALAUTER_UNAVAILABLE = 2
        NOT_ENOUGH_CASH = 3
        BUBU = 4
        xp_increment = 1
        query_base = self.game_query_base
        db = self.mongo.get_db()
        query_find = {}
        query_find.update(query_base)
        orig_data = db['games'].find_one(query_find, {'version': 1, 'nodes_lock': 1, 'game_values': 1, 'active_missions': 1})
        if orig_data is None:
            return {'error': NOT_FOUND}
        game_values = orig_data['game_values']
        active_missions = orig_data.get('active_missions', [])
        version = orig_data.get('version', 1)
        rules = self._get_rules(version=version)
        karmalauters = [k for k in rules.karmalauters if k.get('type_data', {}).get('gestalt', None)==karmalauter and game_values['xp_level']>=k.get('type_data', {}).get('required_level', 0)]
        if len(karmalauters)<1:
            return {'error': KARMALAUTER_UNAVAILABLE}
        karmalauter = karmalauters[0]
        price = karmalauter.get('type_data', {}).get('price', 0)
        if price>game_values['cash_value']:
            return {'error': NOT_ENOUGH_CASH}
        karma_bonus = karmalauter.get('type_data', {}).get('karma_points', 0)
        query_set = {
            '$inc': {
                        'game_values.xp_value': xp_increment,
                        'nodes_lock': 1,
                        'game_values.karma_value': min(karma_bonus, 100-game_values['karma_value']),
                        'game_values.cash_value': -price,
                        'game_values.cash_spent': price
                    },
            '$set': {},
        }
        # reuse query_find
        if orig_data.get('nodes_lock', None) is None:
            query_find.update({'nodes_lock': {'$exists': False}})
        else:
            query_find.update({'nodes_lock': orig_data['nodes_lock']})
        new_xp = game_values['xp_value'] + xp_increment
        # levelup
        levelup, inc_update, set_update, next_levelinfo = self._handle_levelup(new_xp, game_values['xp_value'], version)
        query_set['$inc'].update(inc_update)
        query_set['$set'].update(set_update)

        resp = db['games'].find_and_modify(query=query_find,
                                           update=query_set,
                                           upsert=False,
                                           new=True,
                                           fields={'game_values': 1})
        if resp is None:
            return {'error': BUBU}
        response = {'game_values': resp['game_values']}
        if levelup:
            response.update({'levelup': levelup})
            response['game_values'].update({'ap_initial': next_levelinfo['ap_max']})
            self._log_levelup(active_missions, game_values)
        return response

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def buyPerp(self, token, parent_path, perp_gestalt):
        NOT_FOUND = 1
        NOT_ENOUGH_CASH = 2
        PERP_UNAVAILABLE = 3
        BUBU = 4
        xp_increment = 1
        query_base = self.game_query_base
        db = self.mongo.get_db()
        parent_database = parent_path=='Database'
        if not parent_database:
            query_find = {'nodes.full_path': parent_path}
        else:
            query_find = {}
        query_find.update(query_base)
        orig_data = db['games'].find_one(query_find, {'nodes': 1, 'version': 1, 'nodes_lock': 1, 'game_values': 1, 'mission_goals': 1, 'active_missions': 1})
        if orig_data is None:
            return {'error': NOT_FOUND}
        game_values = orig_data['game_values']
        game_nodes = orig_data['nodes']
        version = orig_data.get('version', 1)
        rules = self._get_rules(version=version)
        perp_data = rules.perps.get(perp_gestalt, rules.tokens.get(perp_gestalt, None))
        if perp_data is None:
            return {'error': PERP_UNAVAILABLE}
        perp_typedata = perp_data.get('type_data', {})
        price = perp_typedata.get('price', 0)
        if game_values['cash_value'] < price:
            return {'error': NOT_ENOUGH_CASH}
        if not parent_database:
            parent_node = [node for node in game_nodes if node['full_path']==parent_path][0]
            parent_gestalt = parent_node['full_type'].split(':')[-1]
            ParentPerp = PerpNode(parent_gestalt, node_data=parent_node, rules=rules, game_id=parent_path.split('.')[-1], game_values=game_values, game_nodes=game_nodes)
        else:
            ParentPerp = PerpNode('__DATABASE__', node_data={'full_path': '__DATABASE__'}, rules=rules, game_id='Database',  game_values=game_values, game_nodes=game_nodes)
        if perp_gestalt not in ParentPerp.get_addable():
           return {'error': PERP_UNAVAILABLE}
        NewPerp = PerpNode(perp_gestalt, node_data={}, rules=rules, game_id=unicode(ObjectId()), game_values=game_values)
        new_node = NewPerp.make_node(parent_path)
        response_extra = {}
        mh = MissionHandler(version,
                            self.session_language,
                            goal_data=orig_data.get('mission_goals', []),
                            active_missions=orig_data.get('active_missions', []),
                            game_nodes=game_nodes,
                            db=db,
                            game_id=orig_data['_id'],
                            game_values=game_values)
        goals_met = mh.handle_buyperp(perp_gestalt)
        rewards = mh.compute_rewards()
        query_set = {
            '$inc': {
                        'game_values.xp_value': xp_increment + rewards.get('xp_value', 0),
                        'nodes_lock': 1,
                        'game_values.cash_value': -price + rewards.get('cash_value', 0),
                        'game_values.cash_spent': price,
                        'game_values.karma_value': min(rewards.get('karma_value', 0), 100-game_values['karma_value'])
                        },
            '$push': {},
            '$set': {
            },
            }
        if goals_met:
            # write new goals, active missions to game
            # add complete missions to response
            # if rewards: handle them
            new_mission_data = {'mission_goals': mh.get_goals(),
                                'active_missions': mh.active_missions}
            query_set['$set'].update(new_mission_data)
            response_extra.update({'missions': {'complete_missions': mh.complete_missions,
                                                'updated_missions': mh.updated_missions,
                                                'mission_data': new_mission_data,
                                                'rewards': rewards}})
            for m in mh.complete_missions:
                self._log_mission_complete(m, game_values)
            profile_sets = rewards.get('profile_sets', [])
            if len(profile_sets)>0:
                query_set['$push'].update({'db_queue': {'$each': profile_sets}})
        if NewPerp.game_type=='CityPerp':
            db_size_inc = NewPerp.city_db_inc
            queue_ps = {'origin': new_node['full_path'],
                        'collect_id': unicode(ObjectId()),
                        'profile_set': NewPerp.add_profileset(),
                        'collect_dt': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)}
            query_set['$push'].update({'db_queue': queue_ps})
            query_set['$inc'].update({'game_values.profiles_max': db_size_inc})
            response_extra.update({'profile_set': queue_ps,})
        query_set['$push'].update({'nodes': new_node})
        new_xp = game_values['xp_value'] + xp_increment + rewards.get('xp_value', 0)
        # levelup
        levelup, inc_update, set_update, next_levelinfo = self._handle_levelup(new_xp, game_values['xp_value'], version)
        query_set['$inc'].update(inc_update)
        query_set['$set'].update(set_update)

        query_find = {'game_values.cash_value': {'$gte': price}}
        if not parent_database:
            query_find.update({'nodes.full_path': parent_path})
        query_find.update(query_base)
        if orig_data.get('nodes_lock', None) is None:
            query_find.update({'nodes_lock': {'$exists': False}})
        else:
            query_find.update({'nodes_lock': orig_data['nodes_lock']})
        resp = db['games'].find_and_modify(query=query_find,
                                           update=query_set,
                                           upsert=False,
                                           new=True,
                                           fields={'game_values': 1, 'nodes': 1})
        if resp is None:
            return {'error': BUBU}
        response = {'node': new_node,
                    'game_values': resp['game_values']}
        response.update(response_extra)
        if levelup:
            response.update({'levelup': levelup})
            response['game_values'].update({'ap_initial': next_levelinfo['ap_max']})
            self._deferred_levelup(level=response['game_values']['xp_level'], version=version, nodes=resp['nodes'])
            self._log_levelup(orig_data.get('active_missions', []), game_values)
        self._deferred_buyperp(level=response['game_values']['xp_level'], version=version, provider_gestalt=perp_gestalt, nodes=game_nodes)
        logAction.apply_async(kwargs={
            'action': 'buyperp',
            'uid': self.auth_uid,
            'time': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC),
            'target': perp_gestalt,
            'level': game_values['xp_level'],
            'xp': game_values['xp_value'],
        })
        return response

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def getProvidedPerps(self, token, perp_full_path):
        """WIP: returns list of gestalten of buyable subperps of parent perp"""
        NOT_FOUND = 0
        query_base = self.game_query_base
        parent_database = perp_full_path=='Database'
        query_find = {}
        if not parent_database:
            query_find = {'nodes.full_path': perp_full_path}
        query_find.update(query_base)
        db = self.mongo.get_db()
        orig_data = db['games'].find_one(query_find, {'nodes': 1, 'version': 1, 'game_values': 1})
        if orig_data is None:
            return {'error': NOT_FOUND}
        game_values = orig_data['game_values']
        game_nodes = orig_data['nodes']
        rules = self._get_rules(version=orig_data.get('version', 1))
        if perp_full_path=='Database':
            node = {'full_path': 'Database'}
            gestalt = '__DATABASE__'
        else:
            node = [node for node in game_nodes if node['full_path']==perp_full_path][0]
            gestalt = node['full_type'].split(':')[-1]
        perp = PerpNode(gestalt, node_data=node, rules=rules, game_id=node['full_path'].split('.')[-1], game_values=game_values, game_nodes=game_nodes)
        return {'buyable': perp.get_addable()}

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def sellPowerup(self, token, perp_full_path, slot, powerup):
        NOT_FOUND = 0
        SLOT_EMPTY = 1
        POWERUP_RULES_FAILURE = 2
        POWERUP_NOT_AVAILABLE = 3
        BUBU = 4
        # sanity
        slot = int(slot)
        xp_increment = 1
        sell_factor = 0.75
        query_base = self.game_query_base
        db = self.mongo.get_db()
        query_find = {'nodes.full_path': perp_full_path}
        query_find.update(query_base)
        orig_data = db['games'].find_one(query_find, {'nodes.$': 1, 'version': 1, 'nodes_lock': 1, 'game_values': 1, 'active_missions': 1})
        if orig_data is None:
            return {'error': NOT_FOUND}
        game_values = orig_data['game_values']
        node_data = orig_data['nodes'][0]
        version = orig_data.get('version', 1)
        rules = self._get_rules(version=version)
        slots = node_data.get('instance_data', {}).get('powerups', [])
        powerups = [p for p in slots if p.get('slot', None)==slot and p.get('gestalt', None)==powerup]
        if len(powerups)<1:
            return {'error': SLOT_EMPTY}
        powerup_data = powerups[0]
        powerup_data = rules.powerups.get(powerup, None)
        if powerup_data is None:
            return {'error': POWERUP_RULES_FAILURE}
        perp_gestalt = node_data['full_type'].split(':')[-1]
        project_typedata = rules.perps[perp_gestalt]['type_data']
        try:
            powerup_type = [p_type for p_type in self.powerup_types if powerup.startswith(p_type)][0]
        except IndexError:
            return {'error': POWERUP_RULES_FAILURE}
        perp_specifics = [data for data in project_typedata.get('provided_%ss' % powerup_type, {}) if data.get('gestalt')==powerup]
        if len(perp_specifics)<1:
            return {'error': POWERUP_RULES_FAILURE}
        powerup_perp_data = perp_specifics[0]
        if game_values['xp_level'] < powerup_perp_data.get('required_level', 0):
            return {'error': POWERUP_NOT_AVAILABLE}
        price = powerup_perp_data.get('price', 0)
        sell_price = int(price*sell_factor)
        # remove modifiers
        # TODO evtl. problem wenn keine werte in instance_data, aber vorinstallierte powerups in default_game
        new_chargecollect_values = dict(('nodes.$.instance_data.%s' % val, node_data.get('instance_data', {}).get(val, project_typedata.get(val)) - powerup_perp_data.get('%s_modifier' % val, 0)) for val in ('charge_cost', 'collect_amount', 'collect_risk'))
        # remove powerup tokens from project result
        old_tokens = node_data.get('instance_data', {}).get('tokens', project_typedata.get('tokens', []))
        new_tokens = powerup_data.get('type_data', {}).get('tokens', [])
        tokens_updated = self._mergeTokens(old_tokens, new_tokens, minus=True)
        new_chargecollect_values.update({'nodes.$.instance_data.tokens': tokens_updated})
        # remove slot
        new_chargecollect_values.update({'nodes.$.instance_data.powerups': [pup for pup in node_data.get('instance_data', {}).get('powerups', []) if not (pup.get('slot')==slot and pup.get('gestalt')==powerup)]})
        # write-out node
        query_set = {
            '$set': new_chargecollect_values,
            '$inc': {
                'game_values.xp_value': xp_increment,
                'nodes_lock': 1,
                'game_values.cash_value': sell_price},
        }
        levelup = False
        new_xp = game_values['xp_value'] + xp_increment
        # levelup
        levelup, inc_update, set_update, next_levelinfo = self._handle_levelup(new_xp, game_values['xp_value'], version)
        query_set['$inc'].update(inc_update)
        query_set['$set'].update(set_update)

        query_find = {'nodes.full_path': perp_full_path}
        query_find.update(query_base)
        if orig_data.get('nodes_lock', None) is None:
            query_find.update({'nodes_lock': {'$exists': False}})
        else:
            query_find.update({'nodes_lock': orig_data['nodes_lock']})
        resp = db['games'].find_and_modify(query=query_find,
                                           update=query_set,
                                           upsert=False,
                                           new=True,
                                           fields={'game_values': 1, 'nodes': 1})
        if resp is None:
            return {'error': BUBU}
        mynode = [node for node in resp['nodes'] if node['full_path']==perp_full_path][0]
        response = {'node': mynode,
                    'game_values': resp['game_values']}
        if levelup:
            response.update({'levelup': levelup})
            response['game_values'].update({'ap_initial': next_levelinfo['ap_max']})
            self._log_levelup(orig_data.get('active_missions', []), game_values)
            self._deferred_levelup(level=response['game_values']['xp_level'], version=version, nodes=resp['nodes'])
        return response

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def buyPowerup(self, token, perp_full_path, slot, powerup):
        """WIP"""
        NOT_FOUND = 0
        SLOT_UNAVAILABLE = 1
        POWERUP_UNAVAILABLE = 2
        NOT_ENOUGH_CASH = 3
        BUBU = 4 # second-check on ap failed, should not happen
        xp_increment = 1
        query_base = self.game_query_base
        db = self.mongo.get_db()
        query_find = {'nodes.full_path': perp_full_path}
        query_find.update(query_base)
        orig_data = db['games'].find_one(query_find, {'nodes.$': 1, 'version': 1, 'nodes_lock': 1, 'game_values': 1, 'mission_goals': 1, 'active_missions': 1})
        if orig_data is None:
            return {'error': NOT_FOUND}
        game_values = orig_data['game_values']
        node_data = orig_data['nodes'][0]
        version = orig_data.get('version', 1)
        rules = self._get_rules(version=version)
        # get powerup data
        powerup_data = rules.powerups.get(powerup, None)
        if powerup_data is None:
            return {'error': POWERUP_UNAVAILABLE}
        perp_gestalt = node_data['full_type'].split(':')[-1]
        project_typedata = rules.perps[perp_gestalt]['type_data']
        try:
            powerup_type = [p_type for p_type in self.powerup_types if powerup.startswith(p_type)][0]
        except IndexError:
            return {'error': POWERUP_UNAVAILABLE}
        perp_specifics = [data for data in project_typedata.get('provided_%ss' % powerup_type, {}) if data.get('gestalt')==powerup]
        if len(perp_specifics)<1:
            return {'error': POWERUP_UNAVAILABLE}
        powerup_perp_data = perp_specifics[0]
        price = powerup_perp_data.get('price', 0)
        if game_values['cash_value'] < price:
            return {'error': NOT_ENOUGH_CASH}
        if game_values['xp_level'] < powerup_perp_data.get('required_level', 0):
            return {'error': POWERUP_UNAVAILABLE}
        installed_powerups = node_data.get('instance_data', {}).get('powerups', [])
        if powerup in [sl.get('gestalt') for sl in installed_powerups]:
            return {'error': POWERUP_UNAVAILABLE}
        available_slots = node_data.get('instance_data', {}).get("%s_slots" % powerup_type, project_typedata.get('%s_slots' % powerup_type, 0))
        used_slots = [p.get('slot') for p in installed_powerups if p.get('gestalt').startswith(powerup_type)]
        slot = int(slot)
        if (slot>=available_slots) or (slot in used_slots):
            return {'error': SLOT_UNAVAILABLE}

        # update node values, add powerup to slot
        new_powerup_slot = {'slot': slot, 'gestalt': powerup, 'full_type': powerup_perp_data['full_type']}
        new_chargecollect_values = dict(('nodes.$.instance_data.%s' % val, node_data.get('instance_data', {}).get(val, project_typedata.get(val)) + powerup_perp_data.get('%s_modifier' % val, 0)) for val in ('charge_cost', 'collect_amount', 'collect_risk'))

        old_tokens = node_data.get('instance_data', {}).get('tokens', project_typedata.get('tokens', []))
        new_tokens = powerup_data.get('type_data', {}).get('tokens', [])
        updated_tokens = self._mergeTokens(old_tokens, new_tokens)

        new_chargecollect_values.update({'nodes.$.instance_data.tokens': updated_tokens})

        response_extra = {}
        mh = MissionHandler(version,
                            self.session_language,
                            goal_data=orig_data.get('mission_goals', []),
                            active_missions=orig_data.get('active_missions', []),
                            game_nodes = None,
                            db=db,
                            game_id=orig_data['_id'],
                            game_values=game_values)
        goals_met = mh.handle_buypowerup(perp_gestalt, powerup)
        rewards = mh.compute_rewards()
        response_extra = {}
        query_set = {
            '$push': {'nodes.$.instance_data.powerups': new_powerup_slot},
            '$set': new_chargecollect_values,
            '$inc': {
                     'game_values.xp_value': xp_increment + rewards.get('xp_value', 0),
                     'nodes_lock': 1,
                     'game_values.cash_value': -price + rewards.get('cash_value', 0),
                     'game_values.cash_spent': price,
                     'game_values.karma_value': min(rewards.get('karma_value', 0), 100-game_values['karma_value'])
                    }
        }
        if goals_met:
            # write new goals, active missions to game
            # add complete missions to response
            # if rewards: handle them
            new_mission_data = {'mission_goals': mh.get_goals(),
                                'active_missions': mh.active_missions}
            query_set['$set'].update(new_mission_data)
            response_extra.update({'missions': {'complete_missions': mh.complete_missions,
                                                'updated_missions': mh.updated_missions,
                                                'mission_data': new_mission_data,
                                                'rewards': rewards}})
            for m in mh.complete_missions:
                self._log_mission_complete(m, game_values)
            profile_sets = rewards.get('profile_sets', [])
            if len(profile_sets)>0:
                query_set['$push'].update({'db_queue': {'$each': profile_sets}})

        levelup = False
        new_xp = game_values['xp_value'] + xp_increment + rewards.get('xp_value', 0)
        # levelup
        levelup, inc_update, set_update, next_levelinfo = self._handle_levelup(new_xp, game_values['xp_value'], version)
        query_set['$inc'].update(inc_update)
        query_set['$set'].update(set_update)

        query_find = {'nodes.full_path': perp_full_path,
                      'game_values.cash_value': {'$gte': price}}
        query_find.update(query_base)
        if orig_data.get('nodes_lock', None) is None:
            query_find.update({'nodes_lock': {'$exists': False}})
        else:
            query_find.update({'nodes_lock': orig_data['nodes_lock']})
        resp = db['games'].find_and_modify(query=query_find,
                                           update=query_set,
                                           upsert=False,
                                           new=True,
                                           fields={'game_values': 1, 'nodes': 1})
        if resp is None:
            return {'error': BUBU}
        mynode = [node for node in resp['nodes'] if node['full_path']==perp_full_path][0]
        response = {'node': mynode,
                    'game_values': resp['game_values']}
        response.update(response_extra)
        if levelup:
            response.update({'levelup': levelup})
            response['game_values'].update({'ap_initial': next_levelinfo['ap_max']})
            self._deferred_levelup(level=response['game_values']['xp_level'], version=version, nodes=resp['nodes'])
            self._log_levelup(orig_data.get('active_missions', []), game_values)
        logAction.apply_async(kwargs={
            'action': 'buypowerup',
            'uid': self.auth_uid,
            'time': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC),
            'target': powerup,
            'project': perp_gestalt,
            'level': game_values['xp_level'],
            'xp': game_values['xp_value'],
        })
        return response

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def getPowerups(self, token, project_type, version):
        """

        :param token: string containing token as acquired by
                      :py:func:`getToken`
        :param project_type: string containing the 'gestalt' id
                             of project
        :returns: json encoded list of powerups for given game_type
        :rtype: json array
        """
        from dd_app.rules import RulesVersion
        r = RulesVersion(version=version, lang=self.session_language)
        return r.get_powerups_for_project(project_type)

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def getTokens(self, token, version):
        """
        :param token: string containing token as acquired by
                      :py:func:`getToken`
        :type token: string
        :param version: integer, game rules version number
        :type version: int
        :returns: json encoded list of tokens for given game version
        :rtype: json array
        """
        return self._get_rules(version=version).tokens

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def setDisplayName(self, token, display_name):
        """
        :param token: string containing token as acquired by
                      :py:func:`getToken`
        :type token: string
        :param display_name: display name to set
        :type display_name: string
        :returns: True if successful
        :rtype: boolean
        """
        oid = self.userdata['_id']
        query_base = {'_id': oid}
        display_name_clean = helpers.validateDisplayName(display_name)
        if display_name_clean is None:
            return {'error': 0}
        db = self.mongo.get_db()
        resp = db['users'].update(query_base, {'$set': {'display_name': display_name_clean}}, safe=True, upsert=False, multi=False)
        if resp.get('n', 0)<1:
            return {'error': 1}
        return True

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def getRanking(self, token, val_type):
        rank_map = {'xp': 'xp_value',
                    'cash': 'cash_value',
                    'profiles': 'profiles_value',
                    'spent': 'cash_spent'}
        # TODO spendings
        field = rank_map.get(val_type, None)
        if field is None:
            return {'error': 0}

        oid = self.userdata['_id']
        tops = self.mongo.get_top_values(field)
        oids = [t['user'] for t in tops]
        display_names = self.mongo.get_display_names_map(oids)
        top = [{'display_name': display_names.get(rec['user'], None), 'value': rec['value'], 'self': rec['user']==oid} for rec in tops]
        rank = self.mongo.get_rank(oid, field)
        return {'top': top,
                'user_rank': rank}

    @dd_protected
    @jsonrpc_method(endpoint='api')
    def logout(self, token):
        """logout django session

        :param token: string containing token as acquired by
                      :py:func:`getToken`
        :type token: string
        :return: True if logged out
        :rtype: json bool

        Removes session from backend, deletes session cookie.
        """
        self._logout()
        return True

    @jsonrpc_method(endpoint='api')
    def ping(self):
        """Pong

        :returns: ``"pong"``
        :rtype: json string
        """
        return 'pong'
