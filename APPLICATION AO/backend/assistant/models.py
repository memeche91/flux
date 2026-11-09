"""Assistant IA local : conversations de l'administrateur et index de recherche."""
from django.conf import settings
from django.db import models


class Conversation(models.Model):
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations")
    titre = models.CharField("titre", max_length=200)
    projet = models.ForeignKey(
        "projets.Projet", null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations",
        help_text="Projet dont les informations sont données à l'assistant.",
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-modifie_le", "-id"]

    def __str__(self):
        return self.titre


class Message(models.Model):
    class Role(models.TextChoices):
        UTILISATEUR = "user", "Utilisateur"
        ASSISTANT = "assistant", "Assistant"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    texte = models.TextField()
    sources = models.JSONField(default=list, blank=True)
    interrompu = models.BooleanField(default=False)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["cree_le", "id"]


class SourcePassage(models.TextChoices):
    ARTICLE = "ARTICLE", "Article de la bibliothèque"
    PRIX = "PRIX", "Prix relevés"
    MODELE = "MODELE", "Modèle de pièce"


class Passage(models.Model):
    """Texte indexé pour la recherche par le sens : article, groupe de prix ou clause de modèle."""

    cle = models.CharField(max_length=255, unique=True)
    source = models.CharField(max_length=10, choices=SourcePassage.choices, db_index=True)
    article = models.ForeignKey("articles.Article", null=True, blank=True, on_delete=models.CASCADE, related_name="passages")
    titre = models.CharField(max_length=500)
    texte = models.TextField()
    meta = models.JSONField(default=dict, blank=True)
    empreinte = models.CharField(max_length=40)
    modele = models.CharField("modèle d'embedding", max_length=100, blank=True)
    vecteur = models.BinaryField(null=True, blank=True)
    maj_le = models.DateTimeField(auto_now=True)


class EtatIndexation(models.Model):
    """Progression de l'indexation (une seule ligne)."""

    en_cours = models.BooleanField(default=False)
    relancer = models.BooleanField(default=False)
    total = models.PositiveIntegerField(default=0)
    faits = models.PositiveIntegerField(default=0)
    message = models.CharField(max_length=500, blank=True)
    debut = models.DateTimeField(null=True, blank=True)
    fin = models.DateTimeField(null=True, blank=True)

    @classmethod
    def courant(cls) -> "EtatIndexation":
        etat, _ = cls.objects.get_or_create(pk=1)
        return etat
