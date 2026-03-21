from django.urls import path

from . import views

app_name = "compressor"

urlpatterns = [
    path("", views.index, name="index"),
    path("upload/", views.upload, name="upload"),
    path("status/<uuid:job_id>/", views.job_status, name="job_status"),
    path("download/<uuid:job_id>/", views.download, name="download"),
]
