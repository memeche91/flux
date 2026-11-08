from django.contrib import admin

from .models import Lot


@admin.register(Lot)
class LotAdmin(admin.ModelAdmin):
    list_display = ("code", "intitule", "ordre", "actif")
    list_editable = ("intitule", "ordre", "actif")
    list_filter = ("actif",)
    search_fields = ("code", "intitule")
