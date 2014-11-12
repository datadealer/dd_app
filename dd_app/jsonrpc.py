"""
Patching pyrmid_jsonrpc to handle HTTPForbidden exceptions
"""

from pyramid_rpc import jsonrpc
from pyramid.httpexceptions import HTTPForbidden
import functools

class JsonRpcUnauthorized(jsonrpc.JsonRpcError):
    """Extends pyramid_rpc.jsonrpc.JsonRpcError,
    represents a 'client unauthorized' exception."""
    code = -32403
    message = 'client unauthorized'

def add_dd_exceptions(f):
    """pyramid_rpc.jsonrpc.exception_view monkeypatcher"""
    @functools.wraps(f)
    def wrapper(exc, request):
        rpc_id = getattr(request, 'rpc_id', None)
        if isinstance(exc, HTTPForbidden):
            fault = JsonRpcUnauthorized()
            jsonrpc.log.debug('json-rpc method unauthorized rpc_id:%s "%s"',
                              rpc_id, request.rpc_method)
            return jsonrpc.make_error_response(request, fault, rpc_id)
        return f(exc, request)
    return wrapper

jsonrpc.exception_view = add_dd_exceptions(jsonrpc.exception_view)
