"""Droits dans la GED.

- Cabinet (comptes Administrateur et Maîtrise d'œuvre) : tout, dont le visa de synthèse.
- Maîtrise d'œuvre associée (BET, architecte co-traitant) : tout voir (zone MOE comprise),
  déposer partout, donner son avis sur un document soumis au visa.
- Entreprise : zone Commun, ses lots (toutes catégories) et, si l'espace le permet, les documents
  techniques des autres lots (jamais les pièces confidentielles : OS, avenants, devis, situations,
  sous-traitance) ; dépôt et nouvel indice dans ses lots seulement.
- Maître d'ouvrage : lecture de tout sauf la zone MOE.
- Contrôleur technique, CSPS, OPC : Commun et documents techniques des lots ; dépôt dans leurs
  catégories (RICT et avis, PGC et DIUO, planning et comptes rendus) ; avis pour le CT et le CSPS.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q

from .categories import APRES_RECEPTION, CATEGORIES, CONFIDENTIELLES, EMISES_PAR_LA_MOE, LECTURE_REQUISE, PAR_CODE
from .models import Acces, Diffusion, Document, EspaceChantier, Intervenant, Profil, RoleAvis, StatutEspace, StatutVisa, Version, Zone

CATEGORIES_PAR_PROFIL = {
    Profil.CONTROLEUR_TECHNIQUE: {"CT"},
    Profil.CSPS: {"SPS", "DIU"},
    Profil.OPC: {"PLG", "CR"},
    Profil.MAITRE_OUVRAGE: set(),
}
ROLE_AVIS = {Profil.MOE_EXTERNE: RoleAvis.BET, Profil.CONTROLEUR_TECHNIQUE: RoleAvis.CONTROLEUR_TECHNIQUE, Profil.CSPS: RoleAvis.CSPS}


@dataclass
class Acteur:
    nom: str
    intervenant: Intervenant | None = None
    acces: Acces | None = None
    utilisateur: object | None = None
    adresse_ip: str | None = None
    navigateur: str = ""
    _lots: set[int] | None = field(default=None, repr=False)

    @property
    def cabinet(self) -> bool:
        return self.intervenant is None

    @property
    def profil(self) -> str | None:
        return self.intervenant.profil if self.intervenant else None

    @property
    def maitrise_oeuvre(self) -> bool:
        return self.cabinet or self.profil == Profil.MOE_EXTERNE

    def lots(self) -> set[int]:
        if self.intervenant is None:
            return set()
        if self._lots is None:
            self._lots = set(self.intervenant.lots.values_list("pk", flat=True))
        return self._lots


def acteur_cabinet(utilisateur, adresse_ip: str | None = None, navigateur: str = "") -> Acteur:
    return Acteur(nom=utilisateur.get_full_name() or utilisateur.username, utilisateur=utilisateur, adresse_ip=adresse_ip, navigateur=navigateur)


def acteur_acces(acces: Acces, adresse_ip: str | None = None, navigateur: str = "") -> Acteur:
    """« Paul Durand (Menuiseries Durand) » : la personne et sa société."""
    intervenant = acces.intervenant
    nom = acces.nom if acces.nom.lower() == intervenant.nom.lower() else f"{acces.nom} ({intervenant.nom})"
    return Acteur(nom=nom[:255], intervenant=intervenant, acces=acces, adresse_ip=adresse_ip, navigateur=navigateur)


def acteur_intervenant(intervenant: Intervenant) -> Acteur:
    """Droits d'un intervenant (sans personne précise) : notifications, contrôles."""
    return Acteur(nom=intervenant.nom, intervenant=intervenant)


# --- Lecture -----------------------------------------------------------------------------

def filtre_visibles(acteur: Acteur, espace: EspaceChantier) -> Q:
    if acteur.maitrise_oeuvre:
        return Q()
    commun = Q(zone=Zone.COMMUN)
    if acteur.profil == Profil.MAITRE_OUVRAGE:
        return commun | Q(zone=Zone.LOT)
    techniques = Q(zone=Zone.LOT) & ~Q(categorie__in=CONFIDENTIELLES)
    if acteur.profil == Profil.ENTREPRISE:
        propres = Q(zone=Zone.LOT, lot_id__in=acteur.lots())
        if not acteur.intervenant.voit_confidentielles:
            propres &= ~Q(categorie__in=CONFIDENTIELLES)  # sous-traitant : pas les pièces chiffrées du titulaire
        return commun | propres | (techniques if espace.lecture_inter_lots else Q(pk__in=[]))
    return commun | techniques


def peut_voir(acteur: Acteur, document: Document) -> bool:
    if acteur.maitrise_oeuvre:
        return True
    if document.zone == Zone.MOE:
        return False
    if document.zone == Zone.COMMUN or acteur.profil == Profil.MAITRE_OUVRAGE:
        return True
    if document.categorie in CONFIDENTIELLES:
        return acteur.profil == Profil.ENTREPRISE and document.lot_id in acteur.lots() and acteur.intervenant.voit_confidentielles
    if acteur.profil == Profil.ENTREPRISE and document.lot_id in acteur.lots():
        return True
    return acteur.profil != Profil.ENTREPRISE or document.espace.lecture_inter_lots


def concerne(acteur: Acteur, document: Document) -> bool:
    """Document qui intéresse l'intervenant au point de lui écrire (et pas seulement lisible)."""
    if not peut_voir(acteur, document):
        return False
    if acteur.profil == Profil.ENTREPRISE:
        return document.zone == Zone.COMMUN or document.lot_id in acteur.lots()
    return True


def voit_avis(acteur: Acteur, version: Version) -> bool:
    """Les avis des co-traitants et du CT restent internes jusqu'au visa de synthèse."""
    if acteur.maitrise_oeuvre or acteur.profil == Profil.CONTROLEUR_TECHNIQUE:
        return True
    return version.visa not in (StatutVisa.EN_ATTENTE, StatutVisa.SANS_OBJET)


# --- Écriture -------------------------------------------------------------------------------

def categories_de_depot(acteur: Acteur) -> set[str]:
    if acteur.maitrise_oeuvre:
        return {c.code for c in CATEGORIES}
    if acteur.profil == Profil.ENTREPRISE:
        return {c.code for c in CATEGORIES if c.zone == "LOT"} - EMISES_PAR_LA_MOE
    return set(CATEGORIES_PAR_PROFIL.get(acteur.profil, set()))


def zones_de_depot(acteur: Acteur) -> list[str]:
    if acteur.maitrise_oeuvre:
        return [Zone.COMMUN, Zone.LOT, Zone.MOE]
    if acteur.profil == Profil.ENTREPRISE:
        return [Zone.LOT]
    return [Zone.COMMUN] if categories_de_depot(acteur) else []


def _categorie_permise(acteur: Acteur, espace: EspaceChantier, categorie: str) -> bool:
    if categorie not in categories_de_depot(acteur):
        return False
    if espace.statut == StatutEspace.RECEPTION and not acteur.cabinet:
        return categorie in APRES_RECEPTION  # après la réception : DOE, DIUO, réserves
    return espace.statut != StatutEspace.CLOS


def peut_deposer(acteur: Acteur, espace: EspaceChantier, zone: str, lot_id: int | None, categorie: str) -> bool:
    if zone not in zones_de_depot(acteur) or not _categorie_permise(acteur, espace, categorie):
        return False
    if zone == Zone.LOT and acteur.profil == Profil.ENTREPRISE:
        return lot_id in acteur.lots()
    return True


def peut_ajouter_indice(acteur: Acteur, document: Document) -> bool:
    if document.annule or not peut_voir(acteur, document):
        return False
    if acteur.maitrise_oeuvre:
        return document.espace.statut != StatutEspace.CLOS
    if document.auteur_intervenant_id != acteur.intervenant.pk:
        return False
    return peut_deposer(acteur, document.espace, document.zone, document.lot_id, document.categorie)


def peut_viser(acteur: Acteur) -> bool:
    """Le visa de synthèse est émis par le cabinet (les co-traitants donnent leur avis)."""
    return acteur.cabinet


def role_avis(acteur: Acteur) -> str | None:
    if acteur.cabinet:
        return RoleAvis.ARCHITECTE
    return ROLE_AVIS.get(acteur.profil)


def peut_donner_avis(acteur: Acteur, version: Version) -> bool:
    if role_avis(acteur) is None or not peut_voir(acteur, version.document):
        return False
    return version.diffusion == Diffusion.POUR_VISA and version.visa == StatutVisa.EN_ATTENTE


def peut_accuser_lecture(acteur: Acteur, version: Version) -> bool:
    document = version.document
    return (
        acteur.profil == Profil.ENTREPRISE and document.categorie in LECTURE_REQUISE
        and document.zone == Zone.LOT and document.lot_id in acteur.lots() and acteur.intervenant.voit_confidentielles
    )


def categorie_valide(code: str) -> bool:
    return code in PAR_CODE
