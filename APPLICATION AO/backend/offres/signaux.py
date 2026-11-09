"""Signaux de l'analyse des offres.

- Les fichiers d'offres sont effacés du disque avec leur fiche (y compris avec le projet ou le lot).
- Une modification des critères, des variantes autorisées ou de la date limite dans les paramètres
  de la consultation change le classement : les propositions validées sont à valider de nouveau.
"""
from django.db import transaction
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from projets.models import Consultation

from .models import Offre
from .notation import invalider_validation

CHAMPS_CLASSEMENT = ("criteres", "variantes_autorisees", "date_limite_offres")


@receiver(post_delete, sender=Offre)
def effacer_fichier(sender, instance, **kwargs):
    if instance.fichier and instance.fichier.name:
        stockage, nom = instance.fichier.storage, instance.fichier.name
        transaction.on_commit(lambda: stockage.delete(nom))


@receiver(pre_save, sender=Consultation)
def classement_modifie(sender, instance, **kwargs):
    if not instance.pk:
        return
    avant = Consultation.objects.filter(pk=instance.pk).values(*CHAMPS_CLASSEMENT).first()
    if avant and any(avant[champ] != getattr(instance, champ) for champ in CHAMPS_CLASSEMENT):
        for lot in instance.projet.lots.all():
            invalider_validation(lot)
