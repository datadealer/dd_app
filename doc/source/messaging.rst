.. _messaging:

*******************
Messaging framework
*******************

.. _messaging-introduction:

------------
Introduction
------------

DataDealer is built as a stack of different, interacting services. The
messaging framework facilitates asynchronous communication between
some of these services:

* ``dd_app`` :ref:`json_rpc`
* ``dd_app`` `Socket.IO`_ handlers
* ``dd_app`` tasks executed by `celery`_ worker
* Datadealer application running on a client, communicating
  with ``dd_app`` over HTTP transport as well as Socket.IO
  transports.

To provide messaging between these components, :ref:`messaging` makes use of a
message broker (currently: Redis PubSub, later: AMQP service) and provides an
easy-to-use interface for server-side components.

.. _messaging-routing

---------------
Message Routing
---------------

.. warning:: Currently, messaging framework only implements a fanout routing 
             for messages, meaning that messages not consumed by consumers
             connected to the backend when the message is issued, are **LOST**.
             Basically, messageing framework is used as a notification service,
             mostly to notify connected clients of some (state|data|...)changes,
             like 'charge cycle finished'.

.. note:: commit d6291637b0bbea8958d3e9cd725d9f0d4cfbe551 provides
          a very basic implementation of persistent point-to-point message queueing.

Server-side components may use the Messenger class **LINKME** to subscribe
and publish to/from messaging channels.

Client application can submit messages to queues indirectly, by calling 
:ref:`json_rpc`. Socket.IO handler acts as a subscriber to certain messages 
and pushes them to the clients.

Specifically, Socket.IO handlers listen to ``srv_msg`` broadcast channel and to
a user-specific channel (for example, ``user_666`` for a user with ``auth_uid`` 
``666``. These are then routed like this:

* ``srv_msg`` messages are pushed to every connected Socket.IO client endpoint
* ``user_xxx`` messages are pushed to every connected Socket.IO client endpoint which
  has been authenticated for user identified by ``xxx`` ``auth_uid``.

.. _messaging-message_format

--------------
Message Format
--------------

Messages are simple mapping objects following this pattern:
::
    {'action': 'ACTION_IDENTIFIER',
     'token': AUTH_TOKEN,
     'data': DATA_MAPPING}

``data`` value (required, can be ``None``) is a mapping containig action-specific data.

``token`` value (optional): string containing ``auth_token`` of the session related to 
the message/action, if applyable.

``action`` value is a unique identifier for message/event type, used by the message
consumer to identify the message and to act accordingly.

.. note:: Message mapping must be serializable by ``bson.json_utils.dumps``

^^^^^^^
Actions
^^^^^^^

.. warning:: This is Work In Progess!!!

Currently, ``dd_app`` components only publish and route the messages. Frontend consumer
supports following types:

* ``debug`` used for debugging

  * ``data`` format: should contain a value with ``message`` key, containig the debug message
  * Frontend consumer outputs debug messages to javascript console.
  * Can be distributed through global broadcast or user-specific channels.

* ``kick`` used to force already open game sessions to close, to avoid issues with multiple game instances.
  Stops messaging listener of recieving socketio handler, closes corresponding socketio connection.

  * ``data`` format: N/A
  * Frontend consumer alerts user and closes the game session
  * Distributed over user-specific channels


* ``node_ready`` used to mark nodes ready to collect after charge and transport charge results to client

  * ``data`` format:
    ::
        {'id': "NODE_ID",            # id of the game node,
         'type': "NODE_TYPE",        # type of the node, ('ContactPerp')
         'path': "some.full.path",   # full path of the node
         'result': <to be specified> # data structure with result, depends on type
        }

  * Frontend consumer marks nodes ready for collecting
  * Distributed over user-specific channels

.. _messaging-api

---
API
---

^^^^^^^
Backend
^^^^^^^

.. todo:: Backend API

^^^^^^^
Message
^^^^^^^

.. todo:: Message wrapper API, serialization etc

^^^^^^^^^
Messenger
^^^^^^^^^

.. todo:: Messenger API, shortcut functions, examples

.. _messaging-examples

------------
API Examples
------------






.. _celery: http://docs.celeryproject.org/en/latest/index.html
.. _Socket.IO: http://socket.io/
