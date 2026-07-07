from functools import wraps

from django.http import JsonResponse


def api_login_required(view):
    """JSON flavour of login_required: 401 instead of a redirect."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "authentication required"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper
