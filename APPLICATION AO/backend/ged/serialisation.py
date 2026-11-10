"""Données renvoyées par l'API de la GED (communes au cabinet et au portail des intervenants)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from dce.assemblage import nom_sur

from .categories import APRES_RECEPTION, CATEGORIES, CONFIDENTIELLES, LECTURE_REQUISE, PAR_CODE
from .droits import (
    Acteur,
    categories_de_depot,
    filtre_visibles,
    peut_accuser_lecture,
    peut_ajouter_indice,
    peut_donner_avis,
    peut_viser,
    role_avis,
    voit_avis,
    zones_de_depot,
)
from .models import (
    AccuseLecture,
    Avis,
    AvisVersion,
    Diffusion,
    Document,
    EspaceChantier,
    Evenement,
    FichierSource,
    Intervenant,
    Profil,
    StatutEspace,
    StatutVisa,
    Version,
    Zone,
)

EN_VIGUEUR, EN_EXAMEN, REFUSEE, REMPLACEE = "EN_VIGUEUR", "EN_EXAMEN", "REFUSEE", "REMPLACEE"
LIBELLES_STATUTS = {EN_VIGUEUR: "À utiliser", EN_EXAMEN: "En examen", REFUSEE: "Refusé : ne pas exécuter", REMPLACEE: "Remplacé"}
# Libellés lus dans un dictionnaire : get_FOO_display() reconstruit le sien à chaque appel (coûteux
# sur les milliers d'indices d'une liste).
LIBELLES_DIFFUSION = dict(Diffusion.choices)
LIBELLES_VISA = dict(StatutVisa.choices)


def statuts_des_versions(versions: list[Version]) -> dict[int, str]:
    """Indice en vigueur : le plus récent qui n'attend pas de visa ou qui a été visé (VSO, VAO, HM).

    Les indices plus récents sont en examen ou refusés ; les plus anciens sont remplacés.
    """
    statuts: dict[int, str] = {}
    trouve = False
    for v in sorted(versions, key=lambda x: (x.deposee_le, x.pk), reverse=True):
        if trouve or v.visa == StatutVisa.REMPLACE:
            statuts[v.pk] = REMPLACEE
        elif v.diffusion != Diffusion.POUR_VISA or v.visa in (StatutVisa.VSO, StatutVisa.VAO, StatutVisa.HM):
            statuts[v.pk] = EN_VIGUEUR
            trouve = True
        else:
            statuts[v.pk] = REFUSEE if v.visa == StatutVisa.REF else EN_EXAMEN
    return statuts


def nom_telechargement(document: Document, version: Version, statut: str) -> str:
    """« 08-EXE-003_C_VAO_Facade nord.pdf » ; « PERIME_… » pour un indice remplacé."""
    extension = Path(version.nom_original).suffix.lower()
    visa = f"_{version.visa}" if version.visa in (StatutVisa.VSO, StatutVisa.VAO, StatutVisa.REF, StatutVisa.HM) else ""
    if statut == REFUSEE:
        visa = "_REFUSE-NE-PAS-EXECUTER"
    base = nom_sur(f"{'PERIME_' if statut == REMPLACEE else ''}{document.reference}_{version.indice}{visa}_{document.titre}", 90)
    return f"{base}{extension}"


def lot_court(lot) -> dict | None:
    return None if lot is None else {"id": lot.pk, "code": lot.code, "intitule": lot.intitule}


@dataclass
class Annexes:
    """Avis, accusés de lecture et fichiers sources des indices d'une liste, regroupés par indice
    (chargés en une requête chacun pour toute la liste)."""

    avis: dict[int, list] = field(default_factory=dict)
    accuses: dict[int, list] = field(default_factory=dict)
    sources: dict[int, list] = field(default_factory=dict)


def version_out(v: Version, document: Document, acteur: Acteur, statut: str, annexes: Annexes | None = None) -> dict:
    espace = document.espace
    attente = v.visa == StatutVisa.EN_ATTENTE
    aujourd_hui = timezone.localdate()
    if annexes is None:
        sources, avis, accuses = v.sources.all(), v.avis.all(), list(v.accuses.all())
    else:
        sources, avis, accuses = annexes.sources.get(v.pk, []), annexes.avis.get(v.pk, []), annexes.accuses.get(v.pk, [])
    donnees = {
        "id": v.pk, "indice": v.indice, "date_indice": v.date_indice, "nom_original": v.nom_original, "taille": v.taille, "empreinte": v.empreinte,
        "objet": v.objet, "deposee_par": v.deposee_par_nom, "deposee_le": v.deposee_le, "diffusion": v.diffusion,
        "diffusion_libelle": LIBELLES_DIFFUSION.get(v.diffusion, v.diffusion), "statut": statut, "statut_libelle": LIBELLES_STATUTS[statut],
        "visa": v.visa, "visa_libelle": LIBELLES_VISA.get(v.visa, v.visa) if v.visa else "", "visa_commentaire": v.visa_commentaire,
        "visa_fichier": bool(v.visa_fichier), "fiche_visa": bool(v.fiche_visa), "vise_par": v.vise_par_nom, "vise_le": v.vise_le,
        "echeance_visa": v.echeance_visa, "visa_en_retard": attente and v.echeance_visa is not None and v.echeance_visa < aujourd_hui,
        "jours_restants": (v.echeance_visa - aujourd_hui).days if attente and v.echeance_visa else None,
        "nouvel_indice_attendu": v.nouvel_indice_attendu, "nom_telechargement": nom_telechargement(document, v, statut),
        "indice_force": v.indice_force, "fichier_archive": not v.fichier,
        "sources": [{"id": s.pk, "nom_original": s.nom_original, "taille": s.taille} for s in sources],
        "avis": [], "peut_donner_avis": not acteur.cabinet and peut_donner_avis(acteur, v) and espace.statut != StatutEspace.CLOS,  # le cabinet vise
        "lecture_requise": document.categorie in LECTURE_REQUISE and document.zone == Zone.LOT, "accuses": [], "lu_le": None,
        "peut_accuser_lecture": peut_accuser_lecture(acteur, v),
    }
    if voit_avis(acteur, v):
        donnees["avis"] = [
            {"id": a.pk, "role": a.role, "role_libelle": a.get_role_display(), "avis": a.avis, "avis_libelle": a.get_avis_display(),
             "observations": a.observations, "fichier": bool(a.fichier), "auteur": a.auteur_nom, "date": a.date}
            for a in avis
        ]
    if acteur.cabinet:
        donnees["accuses"] = [{"intervenant": a.intervenant.nom, "lu_par": a.nom_declare, "lu_le": a.lu_le} for a in accuses]
    else:
        propre = next((a for a in accuses if a.intervenant_id == acteur.intervenant.pk), None)
        donnees["lu_le"] = propre.lu_le if propre else None
    return donnees


def document_out(d: Document, acteur: Acteur, versions: list[Version] | None = None, annexes: Annexes | None = None) -> dict:
    versions = sorted(d.versions.all() if versions is None else versions, key=lambda v: (v.deposee_le, v.pk), reverse=True)
    statuts = statuts_des_versions(versions)
    en_vigueur = next((v for v in versions if statuts[v.pk] == EN_VIGUEUR), None)
    return {
        "id": d.pk, "zone": d.zone, "lot": lot_court(d.lot), "categorie": d.categorie, "categorie_libelle": PAR_CODE[d.categorie].libelle,
        "confidentielle": d.categorie in CONFIDENTIELLES, "reference": d.reference, "reference_emetteur": d.reference_emetteur, "titre": d.titre,
        "auteur": d.auteur_nom, "cree_le": d.cree_le, "annule": d.annule, "motif_annulation": d.motif_annulation,
        "indice_en_vigueur": en_vigueur.indice if en_vigueur else None,
        "versions": [version_out(v, d, acteur, statuts[v.pk], annexes) for v in versions],
        "peut_ajouter_indice": peut_ajouter_indice(acteur, d),
    }


def documents_visibles(espace: EspaceChantier, acteur: Acteur):
    return (
        Document.objects.filter(espace=espace).filter(filtre_visibles(acteur, espace))
        .select_related("lot", "espace__projet").prefetch_related("versions__avis", "versions__accuses__intervenant", "versions__sources")
    )


def _par_parent(objets, cle: str) -> dict[int, list]:
    groupes: dict[int, list] = defaultdict(list)
    for objet in objets:
        groupes[getattr(objet, cle)].append(objet)
    return groupes


def documents_et_versions(espace: EspaceChantier, acteur: Acteur) -> tuple[list[Document], dict[int, list[Version]]]:
    """Documents visibles et leurs indices, en deux requêtes.

    Sans prefetch_related : Django y crée une copie de requête par document et par indice, ce qui
    prenait les deux tiers du temps de la liste d'un gros chantier (2 000 documents, 6 000 indices).
    """
    visibles = Document.objects.filter(espace=espace).filter(filtre_visibles(acteur, espace))
    documents = list(visibles.select_related("lot", "espace__projet"))
    versions = _par_parent(Version.objects.filter(document__in=visibles.values("pk")), "document_id") if documents else {}
    for document in documents:
        for v in versions.get(document.pk, []):
            v.document = document  # droits et noms de téléchargement sans requête par indice
    return documents, versions


def liste_documents(espace: EspaceChantier, acteur: Acteur) -> list[dict]:
    """Liste des documents visibles : exactement document_out pour chacun, en cinq requêtes.

    Pour un intervenant, seuls ses propres accusés de lecture sont chargés (il ne voit pas ceux des
    autres) ; pour le cabinet, tous, avec le nom de l'intervenant.
    """
    documents, versions = documents_et_versions(espace, acteur)
    if not documents:
        return []
    visibles = Document.objects.filter(espace=espace).filter(filtre_visibles(acteur, espace)).values("pk")
    indices = Version.objects.filter(document__in=visibles).values("pk")
    accuses = AccuseLecture.objects.filter(version__in=indices).order_by("pk")
    accuses = accuses.select_related("intervenant") if acteur.cabinet else accuses.filter(intervenant=acteur.intervenant)
    annexes = Annexes(
        avis=_par_parent(AvisVersion.objects.filter(version__in=indices), "version_id"),
        accuses=_par_parent(accuses, "version_id"),
        sources=_par_parent(FichierSource.objects.filter(version__in=indices), "version_id"),
    )
    return [document_out(d, acteur, versions.get(d.pk, []), annexes) for d in documents]


def evenement_out(e: Evenement, cabinet: bool = False) -> dict:
    donnees = {"id": e.pk, "type": e.type, "type_libelle": e.get_type_display(), "date": e.date, "acteur": e.acteur, "description": e.description, "document_id": e.document_id}
    if cabinet:
        donnees.update({"adresse_ip": e.adresse_ip, "notifie_le": e.notifie_le})
    return donnees


def acces_out(a) -> dict:
    return {
        "id": a.pk, "nom": a.nom, "email": a.email, "frequence": a.frequence, "frequence_libelle": a.get_frequence_display(),
        "code_fin": a.code_fin, "code_genere_le": a.code_genere_le, "actif": a.actif, "dernier_acces": a.dernier_acces,
    }


def intervenant_out(i: Intervenant) -> dict:
    return {
        "id": i.pk, "nom": i.nom, "profil": i.profil, "profil_libelle": i.get_profil_display(), "entreprise_id": i.entreprise_id,
        "lots": [lot_court(l) for l in i.lots.all()], "actif": i.actif, "acces": [acces_out(a) for a in i.acces.all()],
        "sous_traitant_de": i.sous_traitant_de_id, "voit_confidentielles": i.voit_confidentielles,
    }


def droits_out(acteur: Acteur, espace: EspaceChantier) -> dict:
    lots = list(espace.projet.lots.order_by("ordre", "code"))
    if acteur.profil == Profil.ENTREPRISE and not espace.lecture_inter_lots:
        lots_visibles = [l for l in lots if l.pk in acteur.lots()]
    else:
        lots_visibles = lots
    zones = zones_de_depot(acteur) if espace.statut != StatutEspace.CLOS else []
    categories = sorted(
        c for c in categories_de_depot(acteur)
        if acteur.cabinet or espace.statut != StatutEspace.RECEPTION or c in APRES_RECEPTION  # après réception : DOE, DIUO, réserves
    ) if zones else []
    if not categories:
        zones = []  # aucune catégorie permise (CT, OPC après la réception) : pas de bouton « Déposer »
    return {
        "zones_visibles": [Zone.COMMUN, Zone.LOT] + ([Zone.MOE] if acteur.maitrise_oeuvre else []),
        "lots": [lot_court(l) for l in lots_visibles],
        "mes_lots": [lot_court(l) for l in lots if l.pk in acteur.lots()],
        "zones_depot": zones,
        "categories_depot": categories,
        "lots_depot": [lot_court(l) for l in lots if Zone.LOT in zones and (acteur.maitrise_oeuvre or l.pk in acteur.lots())],
        "peut_viser": peut_viser(acteur) and espace.statut != StatutEspace.CLOS,
        "peut_donner_avis": role_avis(acteur) is not None and not acteur.cabinet,
        "choix_diffusion": acteur.maitrise_oeuvre,
        "cabinet": acteur.cabinet,
        "statut_espace": espace.statut,
    }


def referentiels() -> dict:
    return {
        "categories": [{"code": c.code, "libelle": c.libelle, "zone": c.zone, "visa": c.visa, "confidentielle": c.confidentielle} for c in CATEGORIES],
        "visas": [{"code": v.value, "libelle": v.label} for v in StatutVisa if v.value not in ("", StatutVisa.EN_ATTENTE)],
        "avis": [{"code": a.value, "libelle": a.label} for a in Avis],
        "diffusions": [{"code": d.value, "libelle": d.label} for d in Diffusion],
        "taille_max_mo": settings.TAILLE_MAX_FICHIER_MO,
    }
