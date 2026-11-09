from django.contrib import admin

from .models import Conversation, Message


class MessageEnLigne(admin.TabularInline):
    model = Message
    extra = 0
    fields = ("role", "texte", "cree_le")
    readonly_fields = ("cree_le",)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("titre", "utilisateur", "projet", "modifie_le")
    inlines = [MessageEnLigne]
