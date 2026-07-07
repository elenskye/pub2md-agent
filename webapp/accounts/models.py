from django.conf import settings
from django.db import models


class ActiveSession(models.Model):
    """The one session each account is allowed (owner's rule: one device
    per account). On login the previous session row is deleted from
    django_session, which instantly signs the old device out — no per-request
    middleware needed."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    session_key = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.user.username} @ {self.created_at:%Y-%m-%d %H:%M}"
