from django.urls import path

from . import views

urlpatterns = [
    path("styles", views.styles),
    path("jobs", views.jobs_collection),
    path("jobs/<uuid:job_id>", views.job_detail),
    path("jobs/<uuid:job_id>/download", views.job_download),
    path("jobs/<uuid:job_id>/files/<str:name>", views.job_file),
]
