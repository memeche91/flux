from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Utilisateur


@admin.register(Utilisateur)
class UtilisateurAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "email", "role", "is_active")
    list_filter = ("role", "is_active", "is_superuser")
    fieldsets = UserAdmin.fieldsets + (("Rôle dans l'application", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Rôle dans l'application", {"fields": ("role",)}),)
