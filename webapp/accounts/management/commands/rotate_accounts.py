"""(Re)generate the two authorized accounts with fresh random passwords.

    python manage.py rotate_accounts

Prints each username/password pair ONCE — hand them to their owners over a
side channel. Rotation also kills the accounts' live sessions, so old
credentials and old logins die together. Account names come from
PUB2MD_ACCOUNTS (comma-separated, default "guest1,guest2").
"""

import os
import secrets

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand

from accounts.models import ActiveSession


class Command(BaseCommand):
    help = "Rotate the authorized accounts' passwords and kill their sessions"

    def handle(self, *args, **options):
        names = [
            n.strip()
            for n in os.getenv("PUB2MD_ACCOUNTS", "guest1,guest2").split(",")
            if n.strip()
        ]
        User = get_user_model()
        for name in names:
            password = secrets.token_urlsafe(9)
            user, _ = User.objects.get_or_create(username=name)
            user.set_password(password)
            user.is_staff = user.is_superuser = False
            user.save()
            active = ActiveSession.objects.filter(user=user).first()
            if active:
                Session.objects.filter(session_key=active.session_key).delete()
                active.delete()
            self.stdout.write(f"{name}: {password}")
        self.stdout.write(self.style.SUCCESS(f"rotated {len(names)} account(s)"))
