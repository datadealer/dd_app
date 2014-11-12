from collections import namedtuple
import json

from dd_app.rules.rulesets import settings
print settings

_SLOTS = ['version', 'perps', 'default_game', 'tokens', 'powerups', 'levels', 'karmalauters', 'karmalizers', 'missions']
Ruleset = namedtuple('Ruleset', _SLOTS)

fp = open('%s/ruleset_3.de.json' % settings.RULEPATH)
data = json.load(fp)
fp.close()

fp = open('%s/default_game.json' % settings.RULEPATH)
default_game = json.load(fp)
fp.close()

RULESET = Ruleset(version=data['version'],
                  perps=data['perps'],
                  default_game=default_game,
                  tokens=data['tokens'],
                  powerups=data['powerups'],
                  levels=data['levels'],
                  karmalizers=data.get('karmalizers', []),
                  karmalauters=data.get('karmalauters', []),
                  missions=data.get('missions', []),
                 )
