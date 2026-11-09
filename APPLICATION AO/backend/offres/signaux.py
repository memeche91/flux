"""Les fichiers d'offres sont effacés du disque avec leur fiche (y compris avec le projet ou le lot)."""
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Offre


@receiver(post_delete, sender=Offre)
def effacer_fichier(sender, instance, **kwargs):
    if instance.fichier and instance.fichier.name:
        stockage, nom = instance.fichier.storage, instance.fichier.name
        transaction.on_commit(lambda: stockage.delete(nom))
