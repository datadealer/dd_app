from dd_app.rules.rulesets import get_ruleset
from bson.objectid import ObjectId
from beaker.cache import cache_region

def mkid():
    return unicode(ObjectId())

def nodeitems_without_children(node):
    return ((k, v) for k, v in node.iteritems() if k!='children')

class RulesNoVersion(Exception):
    pass

class InvalidElem(Exception):
    pass

class ElemRegistry(object):

    def load_elems(self, elems, render_type=None):
        if not hasattr(self, 'data'):
            self.data = {}
        self.data.update(elems)

    def getElem(self, elem_id):
        elem = self.data.get(elem_id, None)
        if elem is None:
            raise InvalidElem('Game definition for %s not found' % elem_id)
        return elem

class RulesVersion(object):

    def __init__(self, game_db=None, version=None, lang=None, **kwargs):
        self.game_db = game_db
        self.version = version
        self.lang = lang

    def set_newgame(self):
        # FIXME hardcoded for now...
        self.version = 1

    @property
    def rules(self):
        if not hasattr(self, '_rules'):
            rs = get_ruleset(self.version, self.lang)
            if rs is None:
                raise RulesNoVersion('No ruleset for version %s' % self.version)
            self._rules = rs
        return self._rules

    @property
    def nodes(self):
        if not hasattr(self, '_nodes'):
            self._nodes = ElemRegistry()
            self._nodes.load_elems(self.rules.perps)
            self._nodes.load_elems(self.rules.view_maps)
            self._nodes.load_elems(self.rules.tokens)
        return self._nodes

    @property
    def missions(self):
        return dict((elem.get('type_data').get('gestalt'), elem) for elem in self.rules.missions)

    def get_next_missions(self, gestalt=0):
        return dict((elem.get('type_data').get('gestalt'), elem) for elem in self.rules.missions if elem.get('type_data').get('required_mission', 0)==gestalt)

    def missions_runtime_data(self, missions):
        """generates initial mission runtime data to be written to game"""
        def mark_goal(goal, mission):
            gl = {}
            gl.update(goal)
            gl.update({'mission': mission.get('type_data', {}).get('gestalt')})
            gl.update({'goal_id': unicode(ObjectId())})
            return gl
        goals = []
        for m in missions:
            goals += [mark_goal(g, m) for g in m.get('type_data', {}).get('goals', [])]
        active_missions = [mission.get('type_data', {}).get('gestalt') for mission in missions]
        return {'mission_goals': goals,
                'active_missions': active_missions}

    def get_powerups_for_project(self, project):
        @cache_region('long_term', 'jsonrpc-getpowerups-%s-%s-%s' % (project, self.version, self.lang))
        def cached_powerups():
            import copy
            node_type_data = self.rules.perps.get(project, {}).get('type_data', {})
            powerups = node_type_data.get('provided_ads', []) + node_type_data.get('provided_teammembers', []) + node_type_data.get('provided_upgrades', [])
            def map_powerups(item):
                powerup = copy.deepcopy(self.rules.powerups.get(item['gestalt']))
                powerup['type_data'].update(item)
                powerup['game_gestalt']=item['gestalt']
                return powerup
            return map(map_powerups, powerups)
        return cached_powerups()

    def get_levelup_notify_perps(self):
        perp_types = ('AgentPerp', 'ContactPerp', 'ProxyPerp', 'ProjectPerp', 'CityPerp',)
        if not hasattr(self, '_levelup_notify_perps'):
            self._levelup_notify_perps = dict((gestalt, data) for gestalt, data in self.rules.perps.items() if data.get('game_type', None) in perp_types)
        return self._levelup_notify_perps

    def get_levelup_items(self, level):
        perps = [gestalt for gestalt, data in self.get_levelup_notify_perps().items() if data.get('type_data', {}).get('required_level', 0)==level]
        return perps

    def get_levelup_powerups(self, level, current_nodes):
        result = {}
        for project_gestalt in current_nodes:
            if project_gestalt.startswith('project'):
                powerups = self.get_powerups_for_project(project_gestalt)
                level_powerups = [p for p in powerups if p.get('type_data', {}).get('required_level', None)==level]
                if len(level_powerups)>0:
                    result[project_gestalt] = level_powerups
        return result

    def get_consumers(self, level=None):
        CONSUMERS = ('PusherPerp', 'ClientPerp')
        if level is None:
            return dict((gestalt, data) for gestalt, data in self.rules.perps.items() if data.get('game_type') in CONSUMERS)
        else:
            return dict((gestalt, data) for gestalt, data in self.rules.perps.items() if data.get('game_type') in CONSUMERS and data.get('type_data', {}).get('required_level', 0) <= level)

    def get_new_consumers_for_provider(self, provider_gestalt, level=0, current_nodes=[]):
        consumers = self.get_consumers(level=level)
        current = set(current_nodes)
        return dict((gestalt, data) for gestalt, data in consumers.items() if provider_gestalt in set(data.get('type_data', {}).get('required_providers', [])) - current)

    def get_new_game(self):
        result = {'version': self.version}
        nodes = []
        separator = '.'
        exceptions = ['tokens', 'game_values']

        def process_leaf(elem, parentpath):
            node_id = mkid()
            path = separator.join((parentpath, node_id))
            node = dict(nodeitems_without_children(elem))
            node['game_id'] = node_id
            node['game_type'] = node['full_type'].split(':')[0]
            node['full_path'] = path
            nodes.append(node)
            for child in elem.get('children', []):
                process_leaf(child, path)

        for leafid, leaf in self.rules.default_game.iteritems():
            path = '%s' % leafid
            if leafid not in exceptions:
                node = dict(nodeitems_without_children(leaf))
                node['full_path'] = path
                node['game_id'] = leafid
                result[leafid] = node
                for child in leaf.get('children', []):
                    process_leaf(child, path)

        result['nodes'] = nodes
        result['game_values'] = self.rules.default_game['game_values']
        import datetime, pytz
        result['game_values']['ap_update'] = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
        result.update(self.missions_runtime_data(self.get_next_missions().values()))
        return result
