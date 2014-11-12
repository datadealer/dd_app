class PerpTypeError(Exception):
    pass


class BasePerp(object):

    CHILD_TYPES = ()

    def __init__(self, gestalt, node_data, rules, game_id, game_values={}, game_nodes=[]):
        self.gestalt = gestalt
        self.rules = rules
        self.game_nodes = game_nodes
        self.game_values = game_values
        self.game_id = game_id

    @property
    def node_type_data(self):
        if not hasattr(self, '_node_type_data'):
            if self.rules is not None:
                self._node_type_data = self.get_typedata_by_gestalt(self.gestalt)
            else:
                self._node_type_data = {}
        return self._node_type_data

    @property
    def node_data(self):
        if not hasattr(self, '_node_data'):
            filtered = [node for node in self.game_nodes if node.get('game_id', '')==self.game_id]
            if len(filtered)>0:
                self._node_data = filtered[0]
            else:
                self._node_data = {}
        return self._node_data

    @property
    def game_type(self):
        return self.node_type_data.get('game_type')

    @property
    def full_type(self):
        return "%s:%s" % (self.game_type, self.gestalt)

    def get_prop(self, prop, *args):
        defval = False
        if len(args)>0:
            default = args[0]
            defval = True
        if defval:
            return self.node_data.get('instance_data', {}).get(prop, self.node_type_data.get('type_data', {}).get(prop, default))
        return self.node_data.get('instance_data', {}).get(prop, self.node_type_data.get('type_data', {}).get(prop))

    def get_typedata_by_gestalt(self, gestalt):
        if self.rules is not None:
            return self.rules.perps[gestalt]
        return {}

    def _check_parent(self, parent):
        return self.game_type in parent.CHILD_TYPES and self.gestalt in parent.get_provided()

    def _check_parent_redundancy(self, parent):
        sibling_gestalten = [node['full_type'].split(':')[-1] for node in self.game_nodes if node.get('full_path', '').startswith("%s." % parent.node_data['full_path'])]
        if self.gestalt in sibling_gestalten:
            return False
        return True

    def _check_level(self):
        if not self.game_values.get('xp_level', 1) < self.node_type_data.get('type_data', {}).get('required_level', 1):
            return True

    def _check_extra_requirements(self):
        return True

    def get_new_instance_data(self):
        return {}

    def make_node(self, parent_path):
        """returns node data"""
        new_node = {}
        new_node.update(self.node_type_data)
        # workaround for tokens
        if new_node.get('gestalt', None) is None:
            new_node['gestalt'] = self.gestalt
        new_node['game_id'] = self.game_id
        new_node['full_type'] = "%s:%s" % (self.game_type, self.gestalt)
        new_node['full_path'] = '.'.join((parent_path, self.game_id))
        del new_node['type_data']
        new_node['instance_data'] = self.get_new_instance_data()
        return new_node

    def get_provided(self):
        """return all available provided perps"""
        # BAD BAD BAD WORKAROUND FOR F(*$#&ED UP SCHEMA, see #303
        gestalten = self.get_prop('provided_perps', [])
        result = []
        for gestalt in gestalten:
            try:
                PerpNode(gestalt, rules=self.rules, game_values=self.game_values, game_nodes=self.game_nodes)
                result.append(gestalt)
            except PerpTypeError:
                pass
        return result

    def get_addable(self):
        instances = (PerpNode(gestalt, rules=self.rules, game_values=self.game_values, game_nodes=self.game_nodes) for gestalt in self.get_provided())
        return [perp.gestalt for perp in instances if perp.check_addable(self)]

    def check_addable(self, parent):
        """returns true if allowed to be created"""
        if self._check_parent(parent):
            if self._check_level():
                if self._check_parent_redundancy(parent):
                    if self._check_extra_requirements():
                        return True
        return False

    def check_theoretical(self):
        return self._check_level() and self._check_extra_requirements()

    @property
    def game_gestalten(self):
        return [node['full_type'].split(':')[-1] for node in self.game_nodes]

    @property
    def token_gestalten(self):
        return [node['gestalt'] for node in self.game_nodes if node['game_type']=='TokenPerp']

    def add_profileset(self):
        return None

class DatabaseSpecialPerp(BasePerp):
    # Parent - none
    # no node_type_data
    # provided - all 
    # provided: alle supertokens
    # alle children nur einmal
    # requirements pro supertoken: tokenrefs mit is_required=True in contained_tokens mit anteil>0 in der database
    CHILD_TYPES = ('TokenPerp',)

    @property
    def node_data(self):
        return {'full_path': ''}

    def get_provided(self):
        perps = [gestalt for gestalt, data in self.rules.tokens.items() if data['game_type'] in self.CHILD_TYPES and data['type_data'].get('is_buyable', False)==True]
        return [perp for perp in perps if perp not in self.token_gestalten]

    def check_addable(self, parent):
        return False


class DatabasePerp(BasePerp):
    CHILD_TYPES = ('CityPerp',)

    def check_addable(self, parent):
        return False

    def get_provided(self):
        # all city perps
        return [gestalt for gestalt, data in self.rules.perps.items() if data['game_type'] in self.CHILD_TYPES]


class CityPerp(BasePerp):
    CHILD_TYPES = ('PusherPerp', 'ProxyPerp', 'AgentPerp')

    def database_values(self):
        td = self.node_type_data.get('type_data', {})
        return {'profiles_max': td.get('profiles_max', 0),
                'profileset_size': td.get('profileset_size', 0)}

    @property
    def city_db_inc(self):
        return self.database_values().get('profiles_max')

    def _tokens_map(self):
        tokens = self.node_type_data.get('type_data', {}).get('tokens')
        return dict((token['gestalt'], {'amount': token['amount']}) for token in tokens if token['amount']>0)

    def add_profileset(self):
        db_vals = self.database_values()
        return {'profiles_value': db_vals['profileset_size'],
                'tokens_map': self._tokens_map()}


class PusherPerp(BasePerp):
    # Parent - city
    # provideds: provided_perps
    # required: parent muss CityPerp sein, required_level muss erreicht sein NEIN, siehe #303
    # zumindest ein client aus provided_perps muss kaufbar sein
    CHILD_TYPES = ('ClientPerp',)

    def _check_level(self):
        return True

    def _check_extra_requirements(self):
        client_gestalten = self.get_provided()
        for cl in client_gestalten:
            try:
                instance = PerpNode(cl, rules=self.rules, game_values=self.game_values, game_nodes=self.game_nodes)
                if instance.check_theoretical():
                    return True
            except PerpTypeError:
                # FIXME BAD BAD BAD WORKAROUND FOR MESSED UP SCHEMA, SEE #303
                pass
        return False


class ClientPerp(BasePerp):
    # parent - pusher
    # provideds: NIX
    # required: parent muss PusherPerp sein,
    #           einer der required_providers muss schon im imperium sein
    #           required_level muss erreicht sein

    def get_addable(self):
        return []

    def get_provided(self):
        return []

    def _check_extra_requirements(self):
        required_providers = self.get_prop('required_providers', [])
        available = self.game_gestalten
        existing = [val for val in required_providers if val in available]
        return len(existing)>0


class AgentPerp(BasePerp):
    # parent - city
    # provided: provided_perps
    # required: parent muss ein CityPerp sein
    #           required_level muss erreicht sein
    CHILD_TYPES = ('ContactPerp',)

class ContactPerp(BasePerp):
    # parent - agent
    # provided: nichts
    # required: parent muss ein AgentPerp sein
    #           required_level muss erreicht sein
    def get_addable(self):
        return []

    def get_provided(self):
        return []

    pass

class ProxyPerp(BasePerp):
    # parent - city
    # provided: provided_perps
    # required: parent muss ein CityPerp sein
    #           required_level muss erreicht sein
    #
    # bekommt extra: in type_data max_slots
    #                in instance_data: free_slots
    CHILD_TYPES = ('ProjectPerp',)

    def _check_parent_redundancy(self, parent):
        sibling_gestalten = [node['full_type'].split(':')[-1] for node in self.game_nodes if node.get('full_path', '').startswith("%s." % parent.node_data['full_path'])]
        gestalten = [g for g in sibling_gestalten if g==self.gestalt]
        max_instances = self.node_type_data.get('type_data', {}).get('max_instances', 1)
        if len(gestalten)> max_instances:
            return False
        return True

    def _get_proxy_projects(self):
        return [node['full_type'].split(':')[-1] for node in self.game_nodes if node.get('full_path', '').startswith("%s." % self.node_data['full_path']) and node['full_type'].startswith('ProjectPerp:')]

    def _get_free_slots(self):
        return self.get_prop('max_slots', 1) - len(self._get_proxy_projects())

class ProjectPerp(BasePerp):
    # parent - proxy
    # provided: nix
    # required: parent muss ein ProxyPerp sein
    #           required_level muss erreicht sein
    #           free_slots>0 in instance_data von proxy-parent 

    def get_addable(self):
        return []

    def get_provided(self):
        return []

    def _get_city_projects(self, city_path):
        return [node['full_type'].split(':')[-1] for node in self.game_nodes if node.get('full_path', '').startswith("%s." % city_path) and node['full_type'].startswith('ProjectPerp:')]

    def _get_city_proxies(self, city_path):
        return [node['full_type'].split(':')[-1] for node in self.game_nodes if node.get('full_path', '').startswith("%s." % city_path) and node['full_type'].startswith('ProxyPerp:')]

    def _check_parent_redundancy(self, parent):
        parents_parent_path = '.'.join(parent.node_data['full_path'].split('.')[:-1])
        sibling_gestalten = self._get_city_projects(parents_parent_path)
        if self.gestalt in sibling_gestalten:
            return False
        return True

    def _check_parent(self, parent):
        return self.game_type in parent.CHILD_TYPES and self.gestalt in parent.get_provided() and parent._get_free_slots()>0

class SuperTokenPerp(BasePerp):
    # parent - 'Database'
    # provided: nix
    # required: parent ist DatabaseSpecialPerp
    #           required_level muss erreicht sein
    #           tokenrefs mit is_required=True in contained_tokens mit anteil>0 in der database
    # FIXME TODO

    def get_addable(self):
        return []

    def get_provided(self):
        return []

    def get_typedata_by_gestalt(self, gestalt):
        if self.rules is not None:
            return self.rules.tokens[gestalt]
        return {}

    def _check_extra_requirements(self):
        contained = self.get_prop('contained_tokens', [])
        available = self._nonzero_token_gestalten
        required = [t['gestalt'] for t in contained if t.get('is_required', False)]
        for token in required:
            if token not in available:
                return False
        return True

    @property
    def _nonzero_token_gestalten(self):
        return [node['gestalt'] for node in self.game_nodes if node['game_type']=='TokenPerp' and node.get('instance_data', {}).get('amount', 0)>0]

    def get_new_instance_data(self):
        return {'amount': 0}

class PerpNode(object):
    registered_classes = {
        'CityPerp': CityPerp,
        'PusherPerp': PusherPerp,
        'ClientPerp': ClientPerp,
        'AgentPerp': AgentPerp,
        'ContactPerp': ContactPerp,
        'ProxyPerp': ProxyPerp,
        'ProjectPerp': ProjectPerp,
        'TokenPerp': SuperTokenPerp,
        'DatabasePerp': DatabasePerp,
        'DatabaseSpecialPerp': DatabaseSpecialPerp,
    }

    def __new__(cls, gestalt, node_data={}, rules=None, game_id=None, game_values={}, game_nodes=[], *args, **kwargs):
        if gestalt=='__DATABASE__':
            game_type = 'DatabaseSpecialPerp'
        else:
            perp_def = rules.perps.get(gestalt, rules.tokens.get(gestalt))
            game_type = perp_def['game_type']
        if game_type in cls.registered_classes:
            return cls.registered_classes[game_type](gestalt, node_data, rules, game_id, game_values, game_nodes, *args, **kwargs)
        raise PerpTypeError('No perp type "%s" registered' % game_type)

