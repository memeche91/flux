"""Droits dans la GED.

- Cabinet (comptes Administrateur et Maîtrise d'œuvre) : tout.
- Maîtrise d'œuvre associée (BET, architecte co-traitant) : tout voir (zone MOE comprise),
  déposer partout, viser ; pas d'annulation ni de gestion des accès.
- Entreprise : zone Commun et ses lots ; dépôt dans ses lots ; nouvel indice sur ses documents.
- Lecture seule (maître d'ouvrage, contrôleur technique, CSPS) : zone Commun et tous les lots.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q

from .models import Document, Intervenant, Profil, Zone


@dataclass
class Acteur:
    nom: str
    intervenant: Intervenant | None = None
    utilisateur: object | None = None

    @property
    def cabinet(self) -> bool:
        return self.intervenant is None

    @property
    def profil(self) -> str | None:
        return self.intervenant.profil if self.intervenant else None

    def lots(self) -> set[int]:
        if self.intervenant is None:
            return set()
        if not hasattr(self, "_lots"):
            self._lots = set(self.intervenant.lots.values_list("pk", flat=True))
        return self._lots


def acteur_cabinet(utilisateur) -> Acteur:
    return Acteur(nom=utilisateur.get_full_name() or utilisateur.username, utilisateur=utilisateur)


def acteur_intervenant(intervenant: Intervenant) -> Acteur:
    return Acteur(nom=intervenant.nom, intervenant=intervenant)


def filtre_visibles(acteur: Acteur) -> Q:
    if acteur.cabinet or acteur.profil == Profil.MOE_EXTERNE:
        return Q()
    if acteur.profil == Profil.LECTEUR:
        return Q(zone__in=[Zone.COMMUN, Zone.LOT])
    return Q(zone=Zone.COMMUN) | Q(zone=Zone.LOT, lot_id__in=acteur.lots())


def peut_voir(acteur: Acteur, document: Document) -> bool:
    if acteur.cabinet or acteur.profil == Profil.MOE_EXTERNE:
        return True
    if document.zone == Zone.MOE:
        return False
    if document.zone == Zone.COMMUN or acteur.profil == Profil.LECTEUR:
        return True
    return document.lot_id in acteur.lots()


def zones_de_depot(acteur: Acteur) -> list[str]:
    if acteur.cabinet or acteur.profil == Profil.MOE_EXTERNE:
        return [Zone.COMMUN, Zone.LOT, Zone.MOE]
    if acteur.profil == Profil.ENTREPRISE:
        return [Zone.LOT]
    return []


def peut_deposer(acteur: Acteur, zone: str, lot_id: int | None) -> bool:
    if zone not in zones_de_depot(acteur):
        return False
    if zone == Zone.LOT and not acteur.cabinet and acteur.profil == Profil.ENTREPRISE:
        return lot_id in acteur.lots()
    return True


def peut_ajouter_indice(acteur: Acteur, document: Document) -> bool:
    if document.annule or not peut_voir(acteur, document):
        return False
    if acteur.cabinet or acteur.profil == Profil.MOE_EXTERNE:
        return True
    return acteur.profil == Profil.ENTREPRISE and document.auteur_intervenant_id == acteur.intervenant.pk and document.lot_id in acteur.lots()


def peut_viser(acteur: Acteur) -> bool:
    return acteur.cabinet or acteur.profil == Profil.MOE_EXTERNE
