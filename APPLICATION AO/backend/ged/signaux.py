"""Les fichiers de la GED sont effacés du disque avec leur fiche (y compris avec le projet)."""
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Version


def _effacer(champ) -> None:
    if champ and champ.name:
        stockage, nom = champ.storage, champ.name
        transaction.on_commit(lambda: stockage.delete(nom))


@receiver(post_delete, sender=Version)
def effacer_fichiers_version(sender, instance, **kwargs):
    _effacer(instance.fichier)
    _effacer(instance.visa_fichier)
