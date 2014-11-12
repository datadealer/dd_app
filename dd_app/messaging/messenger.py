from bson.json_util import dumps, loads

from dd_app.messaging import backend


class Messenger(object):

    def __init__(self, settings={}, backend_class=backend.RedisBackend, uid=None, queues=tuple()):
        self.backend = backend_class(settings=settings)
        self.uid = uid
        assert(isinstance(queues, (list, tuple)))
        self.queues = queues

    def attach(self):
        # Subscribe to fanout channels
        channels = ['srv_msg']
        if self.uid is not None:
            channels.append('user_%s' % self.uid)
        return self.backend.subscribe(channels=channels)

    def get_incoming(self):
        # Generates an iterator over incoming fanout messages
        for m in self.backend.listen():
            data = loads(m['data'])
            yield Message(action = data.get('action', None),
                          token = data.get('token', None),
                          data = data.get('data', None))


    def _send(self, channel, message):
        # Fanout emit
        return self.backend.send(channel, message.serialize())

    def user_send(self, uid, message):
        # Emit to user-specific notification channel
        if uid is not None:
            return self._send('user_%s' % uid, message)

    def broadcast(self, message):
        # Emit to global notification channel
        return self._send('srv_msg', message)

    def _send_queue(self, queue_key, message):
        # Emit to queue
        return self.backend.send_queue(queue_key, message)

    def get_incoming_queue(self):
        # Generates an iterator over incoming queued messages
        for m in self.backend.listen_queue(self.queues):
            data = loads(m['data'])
            yield Message(action = data.get('action', None),
                          token = data.get('token', None),
                          data = data.get('data', None))

    ### Shortcut functions ###

    def kick_user_sessions(self, uid, token=None, sender=None):
        msg = Message(action='kick',
                      token=token,
                      data={'sender': sender})
        return self.user_send(uid, msg)

    def debug(self, msg, token=None, extra_data={}, uid=None):
        data = {'message': msg}
        data.update(extra_data)
        msg = Message(action='debug',
                      token=token,
                      data=data)
        if uid is None:
            # happy broadcast!
            return self.broadcast(msg)
        else:
            return self.user_send(uid, msg)

    def node_ready(self, node_type, uid, node_id, path, result, token=None):
        data = {'id': node_id,
                'type': node_type,
                'path': path,
                'result': result}
        msg = Message(action='node_ready',
                      token=token,
                      data=data)
        return self.user_send(uid, msg)

    def notify_available(self, uid, data={}, token=None):
        msg = Message(action='new_items',
                      token=token,
                      data=data)
        return self.user_send(uid, msg)

class Message(object):

    def __init__(self, *args, **kwargs):
        self.action = kwargs.get('action', None)
        self.token = kwargs.get('token', None)
        self.data = kwargs.get('data', None)

    @property
    def _mapping(self):
        return {'action': self.action,
                'token': self.token,
                'data': self.data}

    def serialize(self):
        return dumps(self._mapping)
