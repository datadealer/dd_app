RULEPATH = 'dd_app/rules/rulesets'

try:
    from dd_app.rules.rulesets.settings_local import *
except ImportError:
    pass
