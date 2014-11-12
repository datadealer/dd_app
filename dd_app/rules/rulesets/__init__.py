from dd_app.rules.rulesets.ruleset_3_de import RULESET as RULESET_3_DE
from dd_app.rules.rulesets.ruleset_3_en import RULESET as RULESET_3_EN

RULES = {
    'en': [RULESET_3_EN, ],
    'de': [RULESET_3_DE, ],
}

def get_ruleset(version, lang):
    res = [rule for rule in RULES.get(lang, RULES.get('en')) if rule.version==version]
    if not res:
        return None
    return res[0]
