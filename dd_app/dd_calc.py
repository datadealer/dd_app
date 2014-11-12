import random
import math

class FeatureFab(object):
    features = []
    total = 0

    @classmethod
    def create(cls, name, upgrades={}, aging = 1, trash = 1):
        if name not in (f.name for f in cls.features):
            feat = Feature(name, upgrades, aging, trash)
            cls.features.append(feat)
            cls.total += 1
            return feat
        else:
            #raise Exception('Feature already exists')
            pass

    @classmethod
    def setCreateMap(cls):
        return ((f, 0) for f in cls.features)


class Feature(object):
    name = None
    upgrades = {}
    aging = 1 # 0>aging>=1, 1 no aging, 0.0001 ultrafast
    trash = 1 # 0>trash>=1, 1 wichtig, 0.0001 ultratrash

    def __init__(self, name, upgrades={}, aging=1, trash=1):
        self.name = name
        self.upgrades = upgrades
        self.aging = aging
        self.trash = trash

    def setAging(self, factor):
        if factor>0 and factor<=1:
            self.aging = factor

    def addUpgrade(self, feature, factor):
        self.upgrades[feature.name] = factor

    def getUpgrades(self, features):
        return dict((feature.name, self.upgrades[feature.name]) for feature in features if self.upgrades.get(feature.name, 0)>0)

    def __unicode__(self):
        return self.name


class ProfileFeature(object):
    feature = None
    share = 0 # 0..100

    def __init__(self, feature, share=0):
        self.feature = feature
        self.share = share

    def setShare(self, share):
        if share<101 and share>-1:
            self.share = share
        else:
            raise ValueError(share)

    @property
    def name(self):
        return self.feature.name

class ProfileSet(object):
    _pfeatures = {}
    number = 0
    origin_id = None # Gewinnspiel, SocialNetwork, ...
    quality = 0 # 0..100
    upgrade_log = {}

    def __init__(self, number, origin_id, quality=100):
        self._pfeatures = {}
        self.upgrade_log = {}
        for feat in FeatureFab.setCreateMap():
            self._pfeatures[feat[0].name] = ProfileFeature(*feat)
        self.number = number
        self.quality = quality
        self.origin_id = origin_id

    @property
    def fill_factor(self):
        return 1

    @property
    def size(self):
        return self.number

    @property
    def features(self):
        return [feat.feature for feat in self._pfeatures.values()]

    @property
    def indicator(self):
        tples = [(x.share*x.feature.trash, x.feature.trash) for x in self._pfeatures.values()]
        if not self.number>0:
            return float(0)
        try:
            indicator = float(sum((i[0] for i in tples)))/float(sum((i[1] for i in tples)))
        except ZeroDivisionError:
            indicator = 0
        indicator = indicator * self.fill_factor
        return indicator

    def __len__(self):
        """
        p = ProfileSet()
        len(p) -> total features
        """
        return len(self._pfeatures.keys())

    def __iter__(self):
        """
        p = ProfileSet()
        [x for x in p] -> ['featname1', 'featname2', ...]
        """
        return self._pfeatures.iterkeys()

    def __getitem__(self,key):
        """
        p = ProfileSet()
        p['featname'] -> get ProfileFeature with name 'featname'
        """
        pf = self._pfeatures.get(key, None)
        if pf is None:
          raise IndexError(key)
        return pf

    def realFeatures(self):
        # returns only features of non-zero share
        return dict((pf.name, pf) for pf in self._pfeatures.values() if pf.share>0)

    def possibleUpgrades(self):
        return dict((pfeature.name, pfeature.feature.getUpgrades(self.features)) for pfeature in self._pfeatures.values())

    def getUpgradersFor(self, pfeature):
        if pfeature not in self._pfeatures.values():
            return {}
        return dict((upgrador.name, pfeature.feature.upgrades[upgrador.name]) for upgrador in self._pfeatures.values() if upgrador.name in pfeature.feature.upgrades.keys())

    def __str__(self):
        out = '------------------------------\n'
        out += "  %s\n" % self.origin_id
        out += "  %s %% total\n" % self.size
        out += "  %s %% quality\n" % round(self.quality, 2)
        out += "  %s %% indicator\n" % round(self.indicator, 2)
        out += "-------Features--------------\n"
        for feat in self.realFeatures().values():
            out += "%.2f %% \t%s\n" % (round(feat.share,2), feat.name)
        out += "-----------------------------"
        return out

class Database(ProfileSet):
    maximum = 1
    mergecount = {}

    @property
    def sizefactor(self):
        if self.maximum > 0:
            return float(self.number)/self.maximum
        else:
            raise ValueError('aetsch')

    @property
    def fill_factor(self):
        return float(self.number)/self.maximum

    @property
    def size(self):
        return round(self.fill_factor*100, 2)

    def setTotal(self, maximum):
        self.maximum = maximum

    def _getMergeCount(self, origin_id):
        count = self.mergecount.get(origin_id, None)
        if count is None:
            count = 0
        return count

    def upgradeFeature(self, feat_name, upgrador_name):
        ##### TUNABLES
        sigmaquad = 0.5
        min_random = 0.85
        max_random = 0.99
        #####
        possible = self.getUpgradersFor(self[feat_name])
        upgrade_factor = possible.get(upgrador_name, None)
        if upgrade_factor is None:
            raise IndexError(upgrador_name)
        pf = self[feat_name]
        up = self[upgrador_name]
        old_upgrades = self.upgrade_log.get(pf.name, {})
        last_upgrade = old_upgrades.get(up.name, 0)
        new_upgrade = float(up.share)/100 * self.number
        up_usable_share = max(0, (new_upgrade - last_upgrade)*100.0/self.number)
        if not up_usable_share>0:
            return False
        dup_raw = float(pf.share)*float(up_usable_share)/100
        dupmax = float(min(pf.share, up_usable_share))
        dup = max(0, min(dupmax, random.gauss(dup_raw, math.sqrt(sigmaquad))))
        better = max(0, up_usable_share - dup)
        new_share = pf.share + (better * upgrade_factor * random.uniform(min_random,max_random))
        overflow = 0
        if new_share>100:
            overflow = 100 - new_share
            new_share = 100
        quality_old = self.quality
        total = len(self._pfeatures.keys())
        f_qfactor = float(1)/total
        # anteil vom verbesserten feature in der qualitaetsrechung
        q_anteil = float(f_qfactor*pf.share)/100
        q_plus = q_anteil*quality_old*float(dup)/100
        q_minus = q_anteil*quality_old*float(overflow)/100
        my_upgrades = self.upgrade_log.get(pf.name, {})
        my_upgrades[up.name] = new_upgrade
        self.upgrade_log[pf.name] = my_upgrades
        pf.setShare(new_share)
        self.quality = max(0, min(100, quality_old+q_plus-q_minus))
        return True



    def merge(self, other, fulldupe=False):
        # TUNABLES
        N = 100000 # mehr -> schwaechere auswirkung von merge count
        M = 0.05 # mehr -> staerkere auswirkung von random 
        if not isinstance(other, ProfileSet):
            raise NotImplemented()
        # NUMBER OF FEATURES
        rand = random.triangular(0, M)
        mergecount = self._getMergeCount(other.origin_id)
        sizefactor = self.sizefactor
        mergefactor = 1-float(1)/((float(mergecount)/N)+1)
        if not fulldupe:
            # MAXIMUM dupes (at least 1 import)
            maxdupes = min(other.number-1, self.number) # can't have more dupes than profiles
            # MINUMUM dupes (for overflow)
            ff = float(self.number)/self.maximum
            mindupes = min(max(int(pow(ff,2)*other.number), self.number + other.number - self.maximum), self.number)
            # real dupes
            dupes = min(maxdupes, mindupes + int(maxdupes * sizefactor * mergefactor + maxdupes*rand))
        else:
            dupes = self.number
        pseudo_increment = other.number - dupes
        new_number = min(self.maximum, self.number + pseudo_increment)
        number_increment = new_number - self.number
        real_dupes = other.number - number_increment
        # QUALITY: merge + dupe-factor
        q_corr = float(self.quality)/100
        if q_corr>0:
            try:
                divisor = float(real_dupes)/(other.number)
                if not divisor > 0:
                    divisor = 0.0000000000001
                dupe_factor = 100*pow(10, math.log10(q_corr)/divisor) #supertoll-quali von dupes! magic!
            except ZeroDivisionError:
                raise ValueError('bubu')
        else:
            dupe_factor = other.quality
        #dupe_factor = 100
        # print dupe_factor*real_dupes
        new_quality = float((self.quality*(self.number-real_dupes)) + (dupe_factor*real_dupes) + (other.quality * number_increment))/(self.number + number_increment)
        # SHARE OF FEATURES
        for pf in other._pfeatures.values():
            db_pf = self._pfeatures.get(pf.name, None)
            if db_pf is None:
                raise IndexError(pf.name)
            share_mix = max(db_pf.share, float(db_pf.share+pf.share)/2) # share on dupes can only rise!!!
            new_share = min(100.0, float(((db_pf.share*(self.number-dupes))+(real_dupes*share_mix)+(pf.share*number_increment))/(self.number + number_increment)))
            db_pf.setShare(new_share)
        self.number += number_increment
        self.quality = new_quality
        # after merge:
        self.mergecount[other.origin_id] = mergecount + 1

