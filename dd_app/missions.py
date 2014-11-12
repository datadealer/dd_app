import datetime, pytz
from bson.objectid import ObjectId
import itertools
import logging

log = logging.getLogger(__name__)

class MissionData(object):

    def __init__(self, goal_data):
        self._mission_dict = dict((goal.get('goal_id'), goal) for goal in goal_data)

    @property
    def _mission_data(self):
        return self._mission_dict.values()

    def goals_for_mission(self, mission):
        return (goal for goal in self._mission_data if goal.get('mission', None)==mission)

    def remove_goals_for_mission(self, mission):
        goal_ids = [goal['goal_id'] for goal in self.goals_for_mission(mission)]
        self.remove_goals(goal_ids)

    def remove_goals(self, goal_ids):
        for gid in goal_ids:
            del self._mission_dict[gid]

    def add_goals(self, goal_data):
        self._mission_dict.update(dict((goal.get('goal_id'), goal) for goal in goal_data))

    def active_goals_for_mission(self, mission):
        return (goal for goal in self.goals_for_mission(mission) if goal.get('complete', False) is not True)

    def mission_done(self, mission):
        goals_left = list(self.active_goals_for_mission(mission))
        return len(goals_left)<1

    @property
    def active_goals(self):
        return [goal for goal in self._mission_data if goal.get('complete', False) is not True]

    def get_active_goals_by_type(self, goaltype):
        return [goal for goal in self.active_goals if goal.get('workflow')==goaltype]

    def get_active_goals(self, goaltype, target, project=False):
        targetvar = 'target' if project is False else 'project'
        return [goal for goal in self.get_active_goals_by_type(goaltype) if goal.get(targetvar, None)==target]

    def get_goal_by_id(self, goalid):
        return self._mission_dict.get(goalid, None)

    def goal_complete(self, goalid):
        self._mission_dict[goalid].update({'complete': True})

    def increment_goal(self, goalid, amount):
        oldval = self._mission_dict[goalid].get('current_amount', 0)
        self._mission_dict[goalid]['current_amount'] = oldval + amount
        if self._mission_dict[goalid].get('amount', 0) <= oldval+amount:
            return True


class MissionHandler(object):

    def __init__(self, version, lang, goal_data=[], active_missions=[], game_nodes=None, db=None, game_id=None, game_values=None):
        self.rules_version = version
        self.lang = lang
        self.mission_data = MissionData(goal_data)
        self.active_missions = active_missions
        self.game_nodes = game_nodes
        self.updated_missions = []
        self.complete_missions = []
        self.db = db
        self.game_id = game_id
        self.extra_perps = []
        self.extra_powerups = {}
        self.extra_token_amounts = {}
        self.rewards = []
        self.game_values = game_values
        self.new_amount = None
        assert((self.game_nodes is not None) or ((self.db is not None) and (self.game_id is not None)))
        assert(game_values is not None)

    def set_new_amount(self, value):
        self.new_amount = value

    def add_extra_perp(self, perp):
        self.extra_perps.append(perp)

    def add_extra_powerup(self, project, powerup):
        self.extra_powerups[project] = self.extra_powerups.get(project, []) + [powerup,]

    def add_extra_tokenamount(self, mapping):
        self.extra_token_amounts.update(mapping)

    @property
    def rules(self):
        if getattr(self, '_rules', None) is None:
            from dd_app.rules import RulesVersion
            self._rules =  RulesVersion(version=self.rules_version, lang=self.lang)
        return self._rules

    @property
    def perp_gestalten(self):
        if getattr(self, '_perps', None) is None:
            if self.game_nodes is not None:
                self._perps = [node['full_type'].split(':')[-1] for node in self.game_nodes]
            else:
                # get gestalten from DB
                resp = self.db.games.aggregate([
                    {'$match': { '_id': self.game_id}},
                    {'$unwind': '$nodes'},
                    {'$group': {'_id': '$_id', 'nodeG': {'$addToSet': '$nodes.full_type'}}},
                ])
                result = resp['result']
                if len(result)<1:
                    self._perps = []
                else:
                    self._perps = [ng.split(':')[-1] for ng in result[0].get('nodeG', [])]
        return self._perps + self.extra_perps

    @property
    def project_powerups(self):
        if getattr(self, '_project_powerups', None) is None:
            self._project_powerups = {}
            if self.game_nodes is not None:
                for node in self.game_nodes:
                    if node['full_type'].startswith('ProjectPerp'):
                        gestalt = node['full_type'].split(':')[-1]
                        self._project_powerups[gestalt] = [sl['gestalt'] for sl in node.get('instance_data', {}).get('powerups', [])]
            else:
                # get data from DB
                resp = self.db.games.aggregate([
                    {'$match': { '_id': self.game_id}},
                    {'$unwind': '$nodes'},
                    {'$group': {'_id': '$nodes.full_type', 'nodeG': {'$addToSet': '$nodes.instance_data.powerups.gestalt'}}},
                ])
                for elem in resp['result']:
                    if len(elem['nodeG']) > 0:
                        self._project_powerups[elem['_id'].split(':')[-1]] = list(itertools.chain.from_iterable(elem['nodeG']))
                    else:
                        self._project_powerups[elem['_id'].split(':')[-1]] = []
        self._project_powerups.update(self.extra_powerups)
        return self._project_powerups

    @property
    def token_amounts(self):
        if getattr(self, '_token_amounts', None) is None:
            self._token_amounts = {}
            if self.game_nodes is not None:
                for node in self.game_nodes:
                    if node['full_type'].startswith('TokenPerp'):
                        gestalt = node['full_type'].split(':')[-1]
                        amount = node.get('instance_data', {}).get('amount', 0)
                        self._token_amounts[gestalt] = amount
            else:
                resp = self.db.games.aggregate([
                    {'$match': { '_id': self.game_id}},
                    {'$unwind': '$nodes'},
                    {'$group': {'_id': '$nodes.full_type', 'amount': {'$sum': '$nodes.instance_data.amount'}}},
                ])
                for elem in resp['result']:
                    gestalt = elem['_id'].split(':')[-1]
                    amount = elem['amount']
                    self._token_amounts[gestalt] = amount
        self._token_amounts.update(self.extra_token_amounts)
        return self._token_amounts

    def mission_updated(self, mission):
        if mission not in self.updated_missions:
            self.updated_missions.append(mission)

    def get_missions_from_goals(self, goal_data):
        return set([goal['mission'] for goal in goal_data])

    def add_mission_data(self, goal_data):
        self.mission_data.add_goals(goal_data)
        for new_mission in self.get_missions_from_goals(goal_data):
            if new_mission not in self.active_missions:
                self.active_missions.append(new_mission)

    def mission_complete(self, mission):
        self.mission_data.remove_goals_for_mission(mission)
        self.active_missions = [am for am in self.active_missions if am!=mission]
        if mission not in self.complete_missions:
            self.complete_missions.append(mission)
        next_data = self.rules.missions_runtime_data(self.rules.get_next_missions(gestalt=mission).values())
        new_goals = next_data.get('mission_goals', [])
        self.add_mission_data(new_goals)
        check_missions = []
        for goal in new_goals:
            if self.check_goal_initial(goal['goal_id']) is True:
                self.mission_data.goal_complete(goal['goal_id'])
                self.mission_updated(goal['mission'])
                check_missions.append(goal['mission'])
        self.post_goal_complete(set(check_missions))

    def check_goal_initial(self, goal_id):
        goal = self.mission_data.get_goal_by_id(goal_id)
        workflow = goal['workflow']
        if workflow=='buy_perp':
            if goal['target'] in self.perp_gestalten:
                return True
        if workflow=='buy_powerup':
            project_powerups = self.project_powerups.get(goal['project'], [])
            if goal['target'] in project_powerups:
                return True
        if workflow=='integrate_profiles':
            token_amount = self.token_amounts.get(goal['target'], 0)
            if goal.get('amount', 0) <= token_amount:
                return True
        return False


    def post_goal_complete(self, missions=[]):
        for mission in missions:
            if self.mission_data.mission_done(mission):
                self.mission_complete(mission)

    def handle_buyperp(self, target_perp):
        match_goals = self.mission_data.get_active_goals('buy_perp', target_perp)
        self.add_extra_perp(target_perp)
        if len(match_goals)<1:
            return False
        for goal in match_goals:
            # those goals are complete
            self.mission_data.goal_complete(goal['goal_id'])
            self.mission_updated(goal['mission'])
        self.post_goal_complete(self.updated_missions[:])
        return True

    def handle_upgradetoken(self, target_perp):
        match_goals = self.mission_data.get_active_goals('upgrade_token', target_perp)
        if len(match_goals)<1:
            return False
        for goal in match_goals:
            self.mission_data.goal_complete(goal['goal_id'])
            self.mission_updated(goal['mission'])
        self.post_goal_complete(self.updated_missions[:])
        return True

    def handle_buypowerup(self, project_perp, target_perp):
        match_goals = self.mission_data.get_active_goals('buy_powerup', project_perp, project=True)
        self.add_extra_powerup(project_perp, target_perp)
        filtered_goals = [g for g in match_goals if g['target']==target_perp]
        if len(filtered_goals)<1:
            return False
        for goal in filtered_goals:
            self.mission_data.goal_complete(goal['goal_id'])
            self.mission_updated(goal['mission'])
        self.post_goal_complete(self.updated_missions[:])
        return True

    def absolute_amount(self, amount):
        if self.new_amount is None:
            profiles = self.game_values.get('profiles_value', 0)
        else:
            profiles = self.new_amount
        return profiles*(float(amount)/100)

    def handle_integrateprofiles(self, target_perp, new_amount):
        match_goals = self.mission_data.get_active_goals('integrate_profiles', target_perp)
        if len(match_goals)<1:
            return False
        update = False
        for goal in match_goals:
            if self.absolute_amount(new_amount) >= goal.get('amount', 0):
                self.mission_data.goal_complete(goal['goal_id'])
            update = True
            self.mission_updated(goal['mission'])
        if update:
            self.post_goal_complete(self.updated_missions[:])
            return True
        return False

    def handle_collectamount(self, target_perp, amount, collect_type):
        match_goals = self.mission_data.get_active_goals(collect_type, target_perp)
        if len(match_goals)<1:
            return False
        update = False
        for goal in match_goals:
            update = True
            full = self.mission_data.increment_goal(goal['goal_id'], amount)
            if full:
                self.mission_data.goal_complete(goal['goal_id'])
            self.mission_updated(goal['mission'])
        if update:
            self.post_goal_complete(self.updated_missions[:])
            return True
        return False

    def handle_chargeperp(self, target_perp):
        match_goals = self.mission_data.get_active_goals('charge_perp', target_perp)
        if len(match_goals)<1:
            return False
        for goal in match_goals:
            # these goals are complete
            self.mission_data.goal_complete(goal['goal_id'])
            self.mission_updated(goal['mission'])
        self.post_goal_complete(self.updated_missions[:])
        return True

    def compute_rewards(self):
        rewards = {
            'ap_value': 0,
            'xp_value': 0,
            'cash_value': 0,
            'karma_value': 0,
            'profile_sets': [],
        }
        for gestalt in self.complete_missions:
            mission = self.rules.missions.get(gestalt, {})
            rewards_data = mission.get('type_data', {}).get('rewards', {})
            for reward in rewards_data:
                if reward['target'] == 'collect_amount':
                    tokens = mission.get('type_data', {}).get('provided_tokens', [])
                    if len(tokens)>0:
                        profileset = {
                            'profiles_value': reward['amount'],
                            'tokens_map': dict((t, {'amount': 100}) for t in tokens),
                        }
                        rewards['profile_sets'].append({'origin': 'Mission.%s' % gestalt,
                                                        'collect_id': unicode(ObjectId()),
                                                        'profile_set': profileset,
                                                        'collect_dt': datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)})
                else:
                    if reward['amount'] is not None:
                        rewards[reward['target']] += reward['amount']
        return rewards

    def get_goals(self):
        return self.mission_data._mission_data


