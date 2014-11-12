class RedisBackend(object):

    def __init__(self, settings={}, *args, **kwargs):
        self.settings = settings

    @property
    def connection(self):
        # cached redis connection
        if not hasattr(self, '_connection'):
            self._connection = self.settings.get('redis.connector').get()
        return self._connection

    @property
    def channel(self):
        # Fanout channel
        if not hasattr(self, '_channel'):
            self._channel = self.connection.pubsub()
        return self._channel

    def subscribe(self, channels=[]):
        # Fanout subscriber
        for chan_id in channels:
            self.channel.subscribe(chan_id)

    def listen(self):
        # Fanout generator
        for m in self.channel.listen():
            if m['type'] == 'message':
                yield m

    def send(self, channel_id, payload):
        # Fanout emitter
        return self.connection.publish(channel_id, payload)

    def listen_queue(self, queue_keys):
        # Message queue generator
        while 1:
            yield self.connection.blpop(queue_keys)

    def send_queue(self, queue_key, payload):
        return self.connection.rpush(payload)
