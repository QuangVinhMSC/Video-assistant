import itertools
import os
from slowapi import Limiter
from slowapi.util import get_remote_address

_counter = itertools.count()

def _key_func(request):
    # Each request gets a unique bucket in test mode so rate limits are never hit.
    if os.environ.get("TESTING"):
        return f"test-{next(_counter)}"
    return get_remote_address(request)

limiter = Limiter(key_func=_key_func)
