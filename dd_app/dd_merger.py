import dd_app.dd_calc as dd

class Merger(object):
    AGING = 1.0
    TRASH = 1.0
    UPGRADES = {}
    QUALITY = 100

    def __init__(self, jargs, fulldupe=False):
        self.args = jargs
        self.fulldupe = fulldupe
        # setup tokens
        for t in self._extract_types(self.args['db_map'], self.args['profileset_map']):
            token = dd.FeatureFab.create(t, upgrades = self.UPGRADES, aging = self.AGING, trash = self.TRASH)
        # setup db
        self.db = dd.Database(int(self.args['db_amount']), 'database', quality = self.QUALITY)
        self.db.maximum = int(self.args['db_max'])
        for t in self.args['db_map']:
            self.db[t['type']].setShare(float(t['amount']))
        # setup profileset
        self.pset = dd.ProfileSet(float(self.args['profileset_amount']), 'profileset', quality = self.QUALITY)
        for t in self.args['profileset_map']:
            self.pset[t['type']].setShare(float(t['amount']))

    def _extract_types(self, dbmap, profmap):
        z = [x['type'] for x in (dbmap+profmap)]
        return list(set(z))

    def merge(self):
        self.db.merge(self.pset, fulldupe=self.fulldupe)
        out = {}
        out['amount'] = self.db.number
        out['mapping'] = [{'type':z.name, 'amount':z.share} for z in self.db.realFeatures().values()]
        out['increment'] = self.db.number - int(self.args['db_amount'])
        out['dup'] = int(self.args['profileset_amount']) - out['increment']
        return out

class UpgradeToken(object):

    def __init__(self, amount, profiles, profiles_max, last_upgrade_data={}, weight=100):
        self.amount = amount
        self.weight = weight
        self.last_upgrade_data = last_upgrade_data
        self.profiles_max = profiles_max
        self.profiles = profiles

    @property
    def amount_multi(self):
        return float(self.amount)/100

    @property
    def amount_absolute(self):
        return self.amount_multi * self.profiles

    @property
    def converted_lastamount(self):
        last_profiles = self.last_upgrade_data.get('profiles_value', 0)
        if last_profiles!=0:
            factor = float(self.profiles)/last_profiles
            if factor!=0:
                return float(self.last_upgrade_data.get('amount', 0))/factor
        return 0

    def get_usable_amount(self):
        return max(0, self.amount - self.converted_lastamount)

    def __add__(self, other):
        args = {'db_max': self.profiles_max,
                'db_amount': self.profiles,
                'profileset_amount': self.profiles,
                'db_map': [{'type': 'foo', 'amount': self.get_usable_amount() * (float(self.weight)/100)},],
                'profileset_map': [{'type': 'foo', 'amount': other.get_usable_amount() * (float(other.weight)/100)},],
               }
        m = Merger(args, fulldupe=False)
        data = m.merge()
        if not data['mapping']:
            data['mapping'] = [{'type': 'foo', 'amount': 0},]
        new_amount_u = data['mapping'][0]['amount']
        new_amount_absolute = float(new_amount_u*data['amount'])/100
        new_amount = min(100, 100*float(new_amount_absolute)/self.profiles)
        return UpgradeToken(new_amount, self.profiles, self.profiles_max)



