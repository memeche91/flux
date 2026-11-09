"""Les fichiers (documents joints, dossiers .zip) sont effacés du disque avec leur fiche,
y compris lors de la suppression d'un projet ou d'un lot."""
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import DossierDCE, PieceJointe


def _effacer(champ) -> None:
    if champ and champ.name:
        stockage, nom = champ.storage, champ.name
        transaction.on_commit(lambda: stockage.delete(nom))


@receiver(post_delete, sender=PieceJointe)
def effacer_piece_jointe(sender, instance, **kwargs):
    _effacer(instance.fichier)


@receiver(post_delete, sender=DossierDCE)
def effacer_dossier(sender, instance, **kwargs):
    _effacer(instance.fichier)
