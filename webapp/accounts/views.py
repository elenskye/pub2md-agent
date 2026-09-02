"""Session-based auth endpoints.

POST /api/login   — {username, password} (form or JSON) → starts the one
                    allowed session for the account, killing any previous one
POST /api/logout  — end the current session
GET  /api/me      — current account, or 401

With PUB2MD_AUTH=off (settings.AUTH_ENABLED False) there is no login wall:
/api/me reports {"auth": false} so the UI can skip the login panel, and the
other two endpoints become no-ops.

CSRF is enforced (Phase 4): clients read the csrftoken cookie planted by
the UI page and echo it in the X-CSRFToken header on every POST.
"""

import json

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.sessions.models import Session
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .decorators import api_login_required
from .models import ActiveSession


def _credentials(request) -> tuple[str, str]:
    if request.content_type == "application/json":
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return "", ""
        return body.get("username", ""), body.get("password", "")
    return request.POST.get("username", ""), request.POST.get("password", "")


@require_POST
def login_view(request):
    if not settings.AUTH_ENABLED:
        return JsonResponse({"auth": False, "username": None})
    username, password = _credentials(request)
    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"error": "invalid credentials"}, status=401)

    login(request, user)
    request.session.save()  # materialize the new session key now

    # Single active session: signing in here signs out everywhere else.
    previous = ActiveSession.objects.filter(user=user).first()
    if previous and previous.session_key != request.session.session_key:
        Session.objects.filter(session_key=previous.session_key).delete()
    ActiveSession.objects.update_or_create(
        user=user, defaults={"session_key": request.session.session_key}
    )
    return JsonResponse({"username": user.username})


@require_POST
@api_login_required
def logout_view(request):
    if not settings.AUTH_ENABLED:
        return JsonResponse({"ok": True})
    ActiveSession.objects.filter(user=request.user).delete()
    logout(request)
    return JsonResponse({"ok": True})


@require_GET
@api_login_required
def me(request):
    if not settings.AUTH_ENABLED:
        return JsonResponse({"auth": False, "username": None})
    return JsonResponse({"auth": True, "username": request.user.username})
