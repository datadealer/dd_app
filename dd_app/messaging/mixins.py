"""Mixins providing messaging functionality
"""

from dd_app.messaging.messenger import Messenger

class MsgMixin():

    @property
    def dd_msg(self):
        if not hasattr(self, '_messenger'):
            self._messenger = self._get_dd_messenger()
        return self._messenger

    def _get_dd_messenger(self):
        # use _get_uid() method (if defined) to fetch user id
        # ALWAYS call this anew in every freshly spawned greenlet!
        return Messenger(uid=getattr(self, '_get_uid', lambda: None)(), settings=self._get_reg_settings())

    def _get_reg_settings(self):
        return self.request.registry.settings
