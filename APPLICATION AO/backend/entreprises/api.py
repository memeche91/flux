"""API de la bibliothèque des entreprises (annuaire)."""
from __future__ import annotations

import csv
import datetime
import io
import re

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.http import content_disposition_header
from ninja import Field, File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from articles.normalisation import normaliser
from referentiel.models import Lot

from .importation import ImportImpossible, doublon, importer
from .models import Contact, Entreprise

router = Router(tags=["Entreprises"])


class LotCourt(Schema):
    id: int
    code: str
    intitule: str


class ContactSchema(Schema):
    id: int | None = None
    nom: str = Field(..., min_length=1, max_length=150)
    fonction: str = Field("", max_length=150)
    email: str = Field("", max_length=254)
    telephone: str = Field("", max_length=30)
    principal: bool = False


class EntrepriseResume(Schema):
    id: int
    raison_sociale: str
    ville: str
    code_postal: str
    telephone: str
    email: str
    lots: list[LotCourt]
    specialites: str
    actif: bool
    contact_principal: str
    nb_consultations: int
    assurance_echue: bool


class Consultation(Schema):
    projet_id: int
    projet: str
    lot: str
    statut: str
    statut_libelle: str
    date: datetime.date | None


class EntrepriseDetail(Schema):
    id: int
    raison_sociale: str
    siret: str
    adresse: str
    code_postal: str
    ville: str
    telephone: str
    email: str
    site_web: str
    lots: list[LotCourt]
    specialites: str
    qualifications: str
    zone_intervention: str
    assureur_decennale: str
    echeance_assurance: datetime.date | None
    notes: str
    actif: bool
    contacts: list[ContactSchema]
    historique: list[Consultation]


class EntrepriseIn(Schema):
    raison_sociale: str = Field(..., min_length=1, max_length=255)
    siret: str = Field("", max_length=20)
    adresse: str = Field("", max_length=255)
    code_postal: str = Field("", max_length=10)
    ville: str = Field("", max_length=120)
    telephone: str = Field("", max_length=30)
    email: str = Field("", max_length=254)
    site_web: str = Field("", max_length=255)
    lot_ids: list[int] = []
    specialites: str = Field("", max_length=500)
    qualifications: str = Field("", max_length=500)
    zone_intervention: str = Field("", max_length=255)
    assureur_decennale: str = Field("", max_length=255)
    echeance_assurance: datetime.date | None = None
    notes: str = ""
    actif: bool = True
    contacts: list[ContactSchema] = []


class BilanImport(Schema):
    creees: int
    mises_a_jour: int
    ignorees: list[str]
    colonnes: dict[str, str]


def _email_valide(valeur: str, libelle: str) -> str:
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    valeur = valeur.strip()
    if valeur:
        try:
            validate_email(valeur)
        except ValidationError:
            raise HttpError(400, f"Adresse e-mail invalide ({libelle}) : « {valeur} ».") from None
    return valeur


def _siret(valeur: str) -> str:
    chiffres = re.sub(r"\D", "", valeur)
    if chiffres and len(chiffres) not in (9, 14):
        raise HttpError(400, "Le SIRET compte 14 chiffres (ou 9 pour un SIREN).")
    return chiffres


def _lots(entreprise: Entreprise) -> list[dict]:
    return [{"id": l.pk, "code": l.code, "intitule": l.intitule} for l in entreprise.lots.all()]


def _historique(entreprise: Entreprise) -> list[dict]:
    from dce.models import ConsultationEntreprise

    return [
        {
            "projet_id": c.projet_id,
            "projet": c.projet.nom,
            "lot": f"Lot {c.lot.code} – {c.lot.intitule}",
            "statut": c.statut,
            "statut_libelle": c.get_statut_display(),
            "date": c.consultee_le,
        }
        for c in ConsultationEntreprise.objects.filter(entreprise=entreprise).select_related("projet", "lot").order_by("-projet__cree_le", "lot__ordre", "lot__code")
    ]


def _detail(entreprise: Entreprise) -> dict:
    return {
        **{champ: getattr(entreprise, champ) for champ in [
            "raison_sociale", "siret", "adresse", "code_postal", "ville", "telephone", "email", "site_web", "specialites",
            "qualifications", "zone_intervention", "assureur_decennale", "echeance_assurance", "notes", "actif",
        ]},
        "id": entreprise.pk,
        "lots": _lots(entreprise),
        "contacts": [
            {"id": c.pk, "nom": c.nom, "fonction": c.fonction, "email": c.email, "telephone": c.telephone, "principal": c.principal}
            for c in entreprise.contacts.all()
        ],
        "historique": _historique(entreprise),
    }


@transaction.atomic
def _enregistrer(entreprise: Entreprise, donnees: EntrepriseIn) -> Entreprise:
    valeurs = donnees.model_dump(exclude={"lot_ids", "contacts"})
    valeurs["raison_sociale"] = " ".join(valeurs["raison_sociale"].split())
    if not valeurs["raison_sociale"]:
        raise HttpError(400, "Indiquez le nom de l'entreprise.")
    valeurs["siret"] = _siret(valeurs["siret"])
    valeurs["email"] = _email_valide(valeurs["email"], "entreprise")
    existante = doublon(valeurs["raison_sociale"], valeurs["siret"], valeurs["code_postal"], valeurs["ville"], exclure=entreprise.pk)
    if existante is not None:
        raise HttpError(409, f"Cette entreprise existe déjà dans l'annuaire : « {existante.raison_sociale} » ({existante.ville or 'ville non renseignée'}).")
    for champ, valeur in valeurs.items():
        setattr(entreprise, champ, valeur.strip() if isinstance(valeur, str) and champ != "notes" else valeur)
    entreprise.save()
    lots = list(Lot.objects.filter(pk__in=donnees.lot_ids))
    if len(lots) != len(set(donnees.lot_ids)):
        raise HttpError(400, "Un des lots choisis n'existe pas.")
    entreprise.lots.set(lots)
    entreprise.contacts.all().delete()
    contacts = [c for c in donnees.contacts if c.nom.strip()]
    principal_vu = False
    for contact in contacts:
        principal = contact.principal and not principal_vu
        principal_vu = principal_vu or principal
        Contact.objects.create(
            entreprise=entreprise, nom=contact.nom.strip(), fonction=contact.fonction.strip(),
            email=_email_valide(contact.email, contact.nom), telephone=contact.telephone.strip(), principal=principal,
        )
    if contacts and not principal_vu:
        Contact.objects.filter(pk__in=entreprise.contacts.order_by("id").values_list("pk", flat=True)[:1]).update(principal=True)
    return entreprise


def _filtrer(recherche: str, lot_id: int | None, actives: bool):
    entreprises = Entreprise.objects.prefetch_related("lots", "contacts").annotate(nb_consultations=Count("consultations", distinct=True))
    if actives:
        entreprises = entreprises.filter(actif=True)
    if lot_id:
        entreprises = entreprises.filter(lots__id=lot_id)
    for mot in normaliser(recherche).split():
        entreprises = entreprises.filter(Q(texte_recherche__contains=mot) | Q(lots__intitule__icontains=mot)).distinct()
    # order_by explicite : Django n'applique pas Meta.ordering à une requête avec Count (liste coupée à 1 000).
    return entreprises.order_by("raison_sociale", "id")


@router.get("/entreprises", response=list[EntrepriseResume])
def lister(request, recherche: str = "", lot_id: int | None = None, actives: bool = False):
    aujourd_hui = timezone.localdate()
    resultat = []
    for e in _filtrer(recherche, lot_id, actives)[:1000]:
        contacts = list(e.contacts.all())
        principal = next((c for c in contacts if c.principal), contacts[0] if contacts else None)
        resultat.append({
            "id": e.pk, "raison_sociale": e.raison_sociale, "ville": e.ville, "code_postal": e.code_postal,
            "telephone": e.telephone, "email": e.email or (principal.email if principal else ""), "lots": _lots(e),
            "specialites": e.specialites, "actif": e.actif, "contact_principal": principal.nom if principal else "",
            "nb_consultations": e.nb_consultations,
            "assurance_echue": bool(e.echeance_assurance and e.echeance_assurance < aujourd_hui),
        })
    return resultat


@router.post("/entreprises", response={201: EntrepriseDetail})
def creer(request, donnees: EntrepriseIn):
    return 201, _detail(_enregistrer(Entreprise(), donnees))


@router.get("/entreprises/export")
def exporter(request):
    flux = io.StringIO()
    ecriture = csv.writer(flux, delimiter=";")
    ecriture.writerow(["Entreprise", "SIRET", "Adresse", "Code postal", "Ville", "Téléphone", "E-mail", "Site", "Lots", "Savoir-faire", "Qualifications", "Contact", "E-mail du contact", "Téléphone du contact", "Active", "Notes"])
    for e in Entreprise.objects.prefetch_related("lots", "contacts"):
        contact = next(iter(e.contacts.all()), None)
        ecriture.writerow([
            e.raison_sociale, e.siret, e.adresse, e.code_postal, e.ville, e.telephone, e.email, e.site_web,
            ", ".join(f"{l.code} {l.intitule}" for l in e.lots.all()), e.specialites, e.qualifications,
            contact.nom if contact else "", contact.email if contact else "", contact.telephone if contact else "",
            "oui" if e.actif else "non", e.notes,
        ])
    reponse = HttpResponse(("﻿" + flux.getvalue()).encode("utf-8"), content_type="text/csv; charset=utf-8")
    reponse["Content-Disposition"] = content_disposition_header(True, f"Annuaire des entreprises {timezone.localdate():%Y-%m-%d}.csv")
    return reponse


@router.post("/entreprises/importer", response=BilanImport)
def importer_fichier(request, fichier: File[UploadedFile]):
    if fichier.size > 20 * 1024 * 1024:
        raise HttpError(400, "Fichier trop volumineux (20 Mo au maximum).")
    try:
        bilan = importer(fichier.name or "", fichier.read())
    except ImportImpossible as erreur:
        raise HttpError(400, str(erreur)) from None
    return {"creees": bilan.creees, "mises_a_jour": bilan.mises_a_jour, "ignorees": bilan.ignorees[:50], "colonnes": bilan.colonnes}


@router.get("/entreprises/{entreprise_id}", response=EntrepriseDetail)
def detail(request, entreprise_id: int):
    return _detail(get_object_or_404(Entreprise.objects.prefetch_related("lots", "contacts"), pk=entreprise_id))


@router.put("/entreprises/{entreprise_id}", response=EntrepriseDetail)
def modifier(request, entreprise_id: int, donnees: EntrepriseIn):
    return _detail(_enregistrer(get_object_or_404(Entreprise, pk=entreprise_id), donnees))


@router.delete("/entreprises/{entreprise_id}", response={204: None})
def supprimer(request, entreprise_id: int):
    entreprise = get_object_or_404(Entreprise, pk=entreprise_id)
    if entreprise.consultations.exists():
        raise HttpError(409, "Cette entreprise a déjà été consultée : désactivez-la plutôt que de la supprimer, pour garder l'historique.")
    entreprise.delete()
    return 204, None
