.. _json_rpc:

****************
JSON-RPC Methods
****************

.. _json_rpc-errors:

-----------
Error codes
-----------

JSON-RPC raw JSON response error for reference::

    {"jsonrpc": "2.0", "id": null, "error": {"message": "client unauthorized", "code": -32403}}

.. py:class:: dd_api.jsonrpc.JsonRpcUnauthorized(code=None, message=None, data=None)

   JSON-RPC error code: -32403

   Means: client is not authorized to access this method. 


For other errors, see `pyramid_rpc Documentation`_.

.. _pyramid_rpc Documentation: http://docs.pylonsproject.org/projects/pyramid_rpc/en/latest/jsonrpc.html#exceptions

.. _json_rpc-api:

============
API Endpoint
============

JSON-RPC methods exposed through API endpoint

----------------------
Authentication methods
----------------------

.. autoclass:: dd_app.views.ApiHandler

    .. automethod:: dd_app.views.ApiHandler.getToken

-----------------
Protected methods
-----------------

.. autoclass:: dd_app.views.ApiHandler

    .. automethod:: dd_app.views.ApiHandler.userData

    .. automethod:: dd_app.views.ApiHandler.loadGame

    .. automethod:: dd_app.views.ApiHandler.setPerpCoordinates

    .. automethod:: dd_app.views.ApiHandler.logout

-----------------
Debugging methods
-----------------

These will be probably removed soon


.. autoclass:: dd_app.views.ApiHandler

    .. automethod:: dd_app.views.ApiHandler.echo

    .. automethod:: dd_app.views.ApiHandler.ping
