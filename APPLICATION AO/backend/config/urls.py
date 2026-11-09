from django.contrib import admin
from django.urls import path

from .api import api

admin.site.site_header = "D’Aplomb — administration"
admin.site.site_title = "D’Aplomb"
admin.site.index_title = "Paramétrage"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
