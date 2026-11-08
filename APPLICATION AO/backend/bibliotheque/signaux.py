from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import DocumentReference


@receiver(post_delete, sender=DocumentReference)
def supprimer_fichier(sender, instance, **kwargs):
    """Supprime le fichier du disque une fois la suppression validée en base."""
    if not instance.fichier:
        return
    stockage, nom = instance.fichier.storage, instance.fichier.name
    transaction.on_commit(lambda: stockage.delete(nom))
