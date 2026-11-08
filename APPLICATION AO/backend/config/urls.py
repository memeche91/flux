from django.contrib import admin
from django.urls import path

from .api import api

admin.site.site_header = "Application AO — administration"
admin.site.site_title = "Application AO"
admin.site.index_title = "Paramétrage"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
