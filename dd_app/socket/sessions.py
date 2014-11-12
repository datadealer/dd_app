from pyramid_sockjs.session import Session

from dd_app.base_handler import BaseHandler
from dd_app.messaging.mixins import MsgMixin

import logging
import uuid
import gevent
import json

log = logging.getLogger(__name__)

class DDSockJSSession(Session, MsgMixin):
    jobs = []

    def on_message(self, message):
        data = json.loads(message)
        event = data.get('ev', None)
        kwargs = data.get('pl', {})
        if event is None:
            log.debug('Message without event information recieved: %s' % message)
            return
        handler = getattr(self, 'onevent_%s' % event, None)
        if handler is None:
            return
        return handler(**kwargs)

    def emit(self, event, payload):
        self.send({'ev': event,
                   'pl': payload})

    def spawn(self, fn, *args, **kwargs):
        log.debug("Spawning sub-Namespace Greenlet: %s" % fn.__name__)
        new = gevent.spawn(fn, *args, **kwargs)
        if getattr(self, 'jobs', None) is None:
            # init jobs
            self.jobs = []
        self.jobs.append(new)
        return new

    def kill_spawned(self):
        gevent.killall(getattr(self, 'jobs', []))
        self.jobs = []

    def _get_uid(self):
        if not hasattr(self, '_uid'):
            hndlr = BaseHandler(self.request)
            self._uid = hndlr.auth_uid
        return self._uid

    def on_open(self):
        pass

    def on_close(self):
        pass

    def onevent_client_connected(self, token=None):
        uid = self._get_uid()
        if uid is not None:
            self._listener_id = unicode(uuid.uuid4())
            self._token = token
            log.debug("Client %s connected" % uid)
            self.dd_msg.kick_user_sessions(uid, token, self._listener_id)
            self.spawn(self.listener, token, uid).link_exception(self._log_error)

    def _log_error(self, glet):
        try:
            glet.get()
        except:
            log.exception('Exception in DDNamespace.listener greenlet')

    def listener(self, token, uid):
        # we need our _own_ messenger instance
        # else we get concurrency problems with backend channel
        messenger = self._get_dd_messenger()
        messenger.attach()
        self.emit('established', {})
        for m in messenger.get_incoming():
            if m.action=='kick':
                if self._listener_id!=m.data.get('sender', False):
                    #log.error(self._listener_id)
                    #log.error(m.data.get('sender', False))
                    self.emit(m.action, m.data)
                    return self.close()
            else:
                self.emit(m.action, m.data)
