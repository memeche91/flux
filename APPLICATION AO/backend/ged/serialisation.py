"""Données renvoyées par l'API de la GED (communes au cabinet et au portail des intervenants)."""
from __future__ import annotations

import datetime

from django.conf import settings
from django.utils import timezone

from .droits import Acteur, filtre_visibles, peut_ajouter_indice, peut_viser, zones_de_depot
from .models import Categorie, Document, EspaceChantier, Evenement, Intervenant, Profil, StatutVisa, Version, Zone


def lot_court(lot) -> dict | None:
    return None if lot is None else {"id": lot.pk, "code": lot.code, "intitule": lot.intitule}


def version_out(v: Version, espace: EspaceChantier) -> dict:
    en_retard = v.visa == StatutVisa.EN_ATTENTE and v.deposee_le + datetime.timedelta(days=espace.delai_visa_jours) < timezone.now()
    return {
        "id": v.pk, "indice": v.indice, "nom_original": v.nom_original, "taille": v.taille, "objet": v.objet,
        "deposee_par": v.deposee_par_nom, "deposee_le": v.deposee_le, "visa": v.visa, "visa_libelle": v.get_visa_display(),
        "visa_commentaire": v.visa_commentaire, "visa_fichier": bool(v.visa_fichier), "visa_nom_original": v.visa_nom_original,
        "vise_par": v.vise_par_nom, "vise_le": v.vise_le, "visa_en_retard": en_retard,
    }


def document_out(d: Document, acteur: Acteur) -> dict:
    versions = sorted(d.versions.all(), key=lambda v: (v.deposee_le, v.pk), reverse=True)
    return {
        "id": d.pk, "zone": d.zone, "lot": lot_court(d.lot), "categorie": d.categorie, "categorie_libelle": d.get_categorie_display(),
        "reference": d.reference, "titre": d.titre, "auteur": d.auteur_nom, "cree_le": d.cree_le,
        "annule": d.annule, "motif_annulation": d.motif_annulation,
        "versions": [version_out(v, d.espace) for v in versions],
        "peut_ajouter_indice": peut_ajouter_indice(acteur, d) and d.espace.statut == "OUVERT",
    }


def documents_visibles(espace: EspaceChantier, acteur: Acteur):
    return (
        Document.objects.filter(espace=espace).filter(filtre_visibles(acteur))
        .select_related("lot", "espace").prefetch_related("versions")
    )


def evenement_out(e: Evenement) -> dict:
    return {
        "id": e.pk, "type": e.type, "type_libelle": e.get_type_display(), "date": e.date, "acteur": e.acteur,
        "description": e.description, "document_id": e.document_id, "notifie_le": e.notifie_le,
    }


def intervenant_out(i: Intervenant) -> dict:
    return {
        "id": i.pk, "nom": i.nom, "profil": i.profil, "profil_libelle": i.get_profil_display(), "entreprise_id": i.entreprise_id,
        "lots": [lot_court(l) for l in i.lots.all()], "emails": i.liste_emails(), "notifications": i.notifications,
        "code_fin": i.code_fin, "code_genere_le": i.code_genere_le, "actif": i.actif, "dernier_acces": i.dernier_acces,
    }


def droits_out(acteur: Acteur, espace: EspaceChantier) -> dict:
    lots = list(espace.projet.lots.order_by("ordre", "code"))
    if acteur.cabinet or acteur.profil in (Profil.MOE_EXTERNE, Profil.LECTEUR):
        lots_visibles = lots
    else:
        lots_visibles = [l for l in lots if l.pk in acteur.lots()]
    zones = zones_de_depot(acteur) if espace.statut == "OUVERT" else []
    return {
        "zones_visibles": [Zone.COMMUN, Zone.LOT] + ([Zone.MOE] if acteur.cabinet or acteur.profil == Profil.MOE_EXTERNE else []),
        "lots": [lot_court(l) for l in lots_visibles],
        "zones_depot": zones,
        "lots_depot": [lot_court(l) for l in lots_visibles if Zone.LOT in zones and (acteur.cabinet or acteur.profil == Profil.MOE_EXTERNE or l.pk in acteur.lots())],
        "peut_viser": peut_viser(acteur) and espace.statut == "OUVERT",
        "cabinet": acteur.cabinet,
    }


def referentiels() -> dict:
    return {
        "categories": [{"code": c.value, "libelle": c.label} for c in Categorie],
        "visas": [{"code": v.value, "libelle": v.label} for v in StatutVisa],
        "taille_max_mo": settings.TAILLE_MAX_FICHIER_MO,
    }
