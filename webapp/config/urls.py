from django.contrib import admin
from django.urls import include, path
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("accounts.urls")),
    path("api/", include("jobs.urls")),
    # Single-page UI; ensure_csrf_cookie plants the token cookie the JS
    # echoes back in the X-CSRFToken header on every POST.
    path("", ensure_csrf_cookie(TemplateView.as_view(template_name="index.html"))),
]
