import random
import itertools

from dd_app import helpers

class CollectablePerpBase(object):

    def __init__(self, node_type_data, node_data, rules, game_values, *args, **kwargs):
        self.node_type_data = node_type_data
        self.node_data = node_data
        self.rules = rules
        self.game_values = game_values
        self.nodes = kwargs.get('nodes', [])

    @property
    def perp_fulltype(self):
        return self.node_data['full_type']

    def getVariatedAmount(self, amount):
        variation = random.random()*10-5
        return int(amount + round((float(amount)/100)*variation))

    def getDBAmounts(self):
        token_amounts = dict((item, 0) for item in self.rules.tokens.keys())
        db_nodes = dict((n['gestalt'], n.get('instance_data', {}).get('amount', 0))
                        for n in self.nodes
                        if n.get('game_type', None)=='TokenPerp')
        token_amounts.update(db_nodes)
        return db_nodes

    def getLevelinfo(self):
        return self.rules.levels[self.game_values['xp_level']-1]

    @property
    def ap_status(self):
        return helpers.calculateAP(self.game_values['ap_snapshot'],
                                   self.game_values['ap_update'],
                                   self.getLevelinfo())


class CollectableToken(CollectablePerpBase):

    @property
    def contained_tokens(self):
        return dict((elem['gestalt'], elem['amount']) for elem in self.node_type_data.get('contained_tokens', []))

    @property
    def contained_tokens_amounts(self):
        tokens = self.contained_tokens
        last = self.last_upgrade_values
        return dict((n['gestalt'], {'amount': n.get('instance_data', {}).get('amount', 0),
                                    'weight': tokens[n['gestalt']],
                                    'last_upgrade_values': {'profiles_value': last.get('profiles_value', 0),
                                                            'amount': last.get('token_map', {}).get(n['gestalt'], 0)},
                                   })
                    for n in self.nodes
                    if n.get('gestalt') in tokens.keys())

    @property
    def last_upgrade_values(self):
        return self.node_data.get('instance_data', {}).get('last_upgrade_values', {})

    def getPerpChargeData(self):
        # get consumed tokens
        from dd_app.dd_merger import UpgradeToken
        gestalt = self.node_data['gestalt']
        old_amount = self.node_data.get('instance_data', {}).get('amount', 0)
        token_data = self.contained_tokens_amounts
        tokens = [UpgradeToken(t['amount'],
                               self.game_values['profiles_value'],
                               self.game_values['profiles_max'],
                               last_upgrade_data=t['last_upgrade_values'],
                               weight=t['weight'])
                  for t in token_data.values()]
        null_token = UpgradeToken(0, self.game_values['profiles_value'], self.game_values['profiles_max'])
        upgraded_token = UpgradeToken(old_amount, self.game_values['profiles_value'], self.game_values['profiles_max'])
        presum = sum(tokens, null_token)
        result = upgraded_token + presum
        token_increment = result.amount - old_amount
        result = {'collect_tokenamount': {gestalt: token_increment},
                  'last_upgrade_data': {'profiles_value': self.game_values['profiles_value'],
                                        'token_map': dict((k, v['amount']) for k, v in token_data.items())},
                 }
        return result, {'ap': 1}


class CollectableContact(CollectablePerpBase):

    @property
    def base_amount(self):
        return self.node_type_data['collect_amount']

    @property
    def base_cost(self):
        return self.node_type_data['charge_cost']

    @property
    def collect_risk(self):
        return self.node_data.get('instance_data', {}).get('collect_risk', self.node_type_data.get('collect_risk', 0))

    def getTokensMap(self, tokens=None):
        if tokens is None:
            tokens = self.node_data.get('instance_data', {}).get('tokens', self.node_type_data['tokens'])
        return dict((token['gestalt'], {'amount': token['amount']}) for token in tokens if token['amount']>0)

    def getPowerupData(self):
        return {'collect_amount': self.base_amount,
                'tokens_map': self.getTokensMap(),
                'charge_cost': {'cash': self.base_cost},
               }

    def getPerpChargeData(self):
        powerup_data = self.getPowerupData()
        result = {'profiles_value': self.getVariatedAmount(powerup_data['collect_amount']),
                  'tokens_map': powerup_data['tokens_map'],
                  'collect_risk': self.collect_risk}
        return result, powerup_data['charge_cost']

class CollectableProject(CollectableContact):

    def getPowerupGestalten(self):
        if getattr(self, '_powerup_gestalten', None) is None:
            self._powerup_gestalten = [p['gestalt'] for p in self.node_data.get('instance_data', {}).get('powerups', [])]
        return self._powerup_gestalten

    def getPowerupMods(self):
        return itertools.chain(*[[d for d in self.rules.powerups.get(gestalt, {}).get('type_data', {}).get('projects', []) if d['full_type']==self.perp_fulltype] for gestalt in self.getPowerupGestalten()])

    def getPowerupData(self):
        collect_amount = self.node_data.get('instance_data', {}).get('collect_amount', self.base_amount)
        charge_cost = self.node_data.get('instance_data', {}).get('charge_cost', self.base_cost)
        tokens_map = self.getTokensMap()

        return {'collect_amount': collect_amount,
                'tokens_map': tokens_map,
                'charge_cost': {'cash': charge_cost}
               }


class CollectableClient(CollectablePerpBase):

    def getCost(self):
        return {'ap': 1}

    def getPerpChargeData(self):
        db_state = self.getDBAmounts()
        token_amounts = [float(db_state.get(token['gestalt'], 0) * token['amount'])/10000 for token in self.node_type_data['consumed_tokens']]
        amount = sum(token_amounts, 0)
        db_fill_factor = self.getDBFactorNormalized(db_state)
        karma_penalty_factor = self.getKarmaPenalty()
        amount = (amount * db_fill_factor)**0.6
        #result = int(karma_penalty_factor * round((self.node_type_data['income_base'] + (amount * self.node_type_data['income_base'] * (float(self.node_type_data['income_factor'])/1000)))/10)*10)
        result = int(karma_penalty_factor * round((self.node_type_data['income_base'] + (amount * self.node_type_data['income_base'] * (float(self.node_type_data['income_factor'])/1000)))))
        return {'collect_cash': result}, self.getCost()

    def getKarmaPenalty(self):
        karma = self.game_values.get('karma_value', 0)
        karma_factor = float(karma + 100)/200 + 0.5
        return min(1, karma_factor)

    def _getCityGestalten(self):
        return [node.get('full_type').split(':')[-1] for node in self.nodes if node['game_type']=='CityPerp']

    def _getCityOriginAmounts(self, amounts):
        cities = self._getCityGestalten()
        city_amounts = {}
        for origin_gestalt, origin_data in self.rules.tokens.items():
            city_gestalt = origin_data.get('type_data', {}).get('origin_gestalt', None)
            if city_gestalt in cities:
                # city amount normalized to max city profiles
                city_max = self.rules.perps.get(city_gestalt).get('type_data').get('profiles_max')
                city_amounts[city_gestalt] = ((float(amounts.get(origin_gestalt, 0))/100) * self.game_values.get('profiles_value')) / city_max
        return city_amounts

    def getDBFactorNormalized(self, db_amounts):
        city_amounts = self._getCityOriginAmounts(db_amounts)
        return float(sum(city_amounts.values()))


class CollectablePerp(object):
    """Factory class for CollectablePerpBase subclasses"""
    registered_classes = {
        'ContactPerp': CollectableContact,
        'ProjectPerp': CollectableProject,
        'ClientPerp': CollectableClient,
        'TokenPerp': CollectableToken,
    }

    def __new__(cls, node_type_data, node_data, rules, *args, **kwargs):
        game_type = node_data.get('game_type', None)
        if game_type in cls.registered_classes:
            return cls.registered_classes[game_type](node_type_data, node_data, rules, *args, **kwargs)
        else:
            return None
