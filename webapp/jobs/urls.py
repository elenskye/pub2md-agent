from django.urls import path

from . import views

urlpatterns = [
    path("styles", views.styles),
    path("jobs", views.create_job),
    path("jobs/<uuid:job_id>", views.job_detail),
    path("jobs/<uuid:job_id>/download", views.job_download),
]
