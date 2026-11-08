from django.contrib import admin

from .models import Article, LignePrix


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("numero", "titre", "lot", "categorie", "document")
    list_filter = ("categorie", "lot", "document__type_document")
    search_fields = ("titre", "contenu")
    list_select_related = ("lot", "document")
    raw_id_fields = ("document",)


@admin.register(LignePrix)
class LignePrixAdmin(admin.ModelAdmin):
    list_display = ("designation", "unite", "quantite", "prix_unitaire", "lot", "document")
    list_filter = ("lot", "unite_normalisee")
    search_fields = ("designation",)
    list_select_related = ("lot", "document")
    raw_id_fields = ("document",)
