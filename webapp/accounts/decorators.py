from functools import wraps

from django.conf import settings
from django.http import JsonResponse


def api_login_required(view):
    """JSON flavour of login_required: 401 instead of a redirect.

    A no-op when settings.AUTH_ENABLED is False (PUB2MD_AUTH=off, local
    single-user runs). The setting is read per request so tests can flip it
    with override_settings.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if settings.AUTH_ENABLED and not request.user.is_authenticated:
            return JsonResponse({"error": "authentication required"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper
