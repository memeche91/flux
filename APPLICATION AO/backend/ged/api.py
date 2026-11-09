"""API de la GED côté cabinet (comptes Administrateur et Maîtrise d'œuvre)."""
from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.shortcuts import get_object_or_404
from ninja import Field, File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from dce.models import ConsultationEntreprise, StatutConsultation
from entreprises.models import Entreprise
from projets.models import Projet

from . import vues
from .acces import attribuer_code
from .droits import acteur_cabinet
from .models import Document, EspaceChantier, Intervenant, Profil, StatutEspace, TypeEvenement
from .serialisation import document_out, droits_out, intervenant_out, referentiels
from .services import annuler, journaliser, retablir

router = Router(tags=["GED de chantier"])


class IntervenantIn(Schema):
    entreprise_id: int | None = None
    nom: str = Field("", max_length=255)
    profil: Profil = Profil.ENTREPRISE
    lot_ids: list[int] = []
    emails: list[str] = []
    notifications: bool = True


class OuvertureIn(Schema):
    intervenants: list[IntervenantIn] = []


class EspaceIn(Schema):
    notifications: bool | None = None
    emails_moe: list[str] | None = None
    message_accueil: str | None = Field(None, max_length=4000)
    delai_visa_jours: int | None = Field(None, ge=1, le=90)


class ModificationIntervenant(Schema):
    nom: str | None = Field(None, max_length=255)
    profil: Profil | None = None
    lot_ids: list[int] | None = None
    emails: list[str] | None = None
    notifications: bool | None = None
    actif: bool | None = None


class CodeIn(Schema):
    envoyer: bool = False


class ModificationDocument(Schema):
    titre: str | None = Field(None, max_length=255)
    reference: str | None = Field(None, max_length=60)
    categorie: str | None = None
    annule: bool | None = None
    motif_annulation: str | None = Field(None, max_length=500)


def _espace(espace_id: int) -> EspaceChantier:
    return get_object_or_404(EspaceChantier.objects.select_related("projet"), pk=espace_id)


def _emails(liste: list[str]) -> str:
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError

    propres = []
    for adresse in liste:
        adresse = adresse.strip()
        if not adresse:
            continue
        try:
            validate_email(adresse)
        except ValidationError:
            raise HttpError(400, f"Adresse e-mail invalide : {adresse}") from None
        propres.append(adresse)
    return "\n".join(dict.fromkeys(propres))


def _suggestions(projet: Projet, espace: EspaceChantier | None) -> list[dict]:
    """Entreprises retenues à l'analyse des offres, avec leurs lots, pas encore intervenantes."""
    deja = set(espace.intervenants.exclude(entreprise=None).values_list("entreprise_id", flat=True)) if espace else set()
    par_entreprise: dict[int, dict] = {}
    for c in ConsultationEntreprise.objects.filter(projet=projet, statut=StatutConsultation.RETENUE).select_related("entreprise", "lot").prefetch_related("entreprise__contacts"):
        if c.entreprise_id in deja:
            continue
        fiche = par_entreprise.setdefault(c.entreprise_id, {
            "entreprise_id": c.entreprise_id, "nom": c.entreprise.raison_sociale, "lots": [],
            "emails": [e for e in [c.entreprise.email, *(x.email for x in c.entreprise.contacts.all())] if e][:3],
        })
        fiche["lots"].append({"id": c.lot_id, "code": c.lot.code, "intitule": c.lot.intitule})
    return sorted(par_entreprise.values(), key=lambda f: f["nom"])


def _espace_out(espace: EspaceChantier, request) -> dict:
    acteur = acteur_cabinet(request.auth)
    documents = list(espace.documents.prefetch_related("versions"))
    en_attente = sum(1 for d in documents if not d.annule and any(v.visa == "EN_ATTENTE" for v in d.versions.all()[:1]))
    return {
        "id": espace.pk, "statut": espace.statut, "ouvert_le": espace.ouvert_le, "notifications": espace.notifications,
        "emails_moe": espace.liste_emails_moe(), "message_accueil": espace.message_accueil, "delai_visa_jours": espace.delai_visa_jours,
        "intervenants": [intervenant_out(i) for i in espace.intervenants.prefetch_related("lots")],
        "droits": droits_out(acteur, espace),
        "statistiques": {"documents": len(documents), "en_attente_visa": en_attente},
    }


def _etat(projet: Projet, request) -> dict:
    espace = EspaceChantier.objects.filter(projet=projet).first()
    return {
        "projet": {"id": projet.pk, "nom": projet.nom, "type_marche": projet.type_marche},
        "espace": _espace_out(espace, request) if espace else None,
        "suggestions": _suggestions(projet, espace),
        "email_actif": settings.EMAIL_ACTIF,
        "url_publique": settings.GED_URL_PUBLIQUE,
        **referentiels(),
    }


def _creer_intervenant(espace: EspaceChantier, donnees: IntervenantIn, request) -> tuple[Intervenant, str]:
    entreprise = get_object_or_404(Entreprise, pk=donnees.entreprise_id) if donnees.entreprise_id else None
    nom = (donnees.nom or (entreprise.raison_sociale if entreprise else "")).strip()
    if not nom:
        raise HttpError(400, "Indiquez le nom de l'intervenant.")
    lots = list(espace.projet.lots.filter(pk__in=donnees.lot_ids))
    if len(lots) != len(set(donnees.lot_ids)):
        raise HttpError(400, "Lot inconnu pour ce chantier.")
    if donnees.profil == Profil.ENTREPRISE and not lots:
        raise HttpError(400, "Choisissez au moins un lot pour une entreprise.")
    emails = donnees.emails or ([entreprise.email] if entreprise and entreprise.email else [])
    intervenant = Intervenant.objects.create(
        espace=espace, entreprise=entreprise, nom=nom[:255], profil=donnees.profil, emails=_emails(emails), notifications=donnees.notifications,
    )
    intervenant.lots.set(lots)
    code = attribuer_code(intervenant)
    journaliser(espace, TypeEvenement.ACCES, f"Accès ouvert pour {intervenant.nom} ({intervenant.get_profil_display()})", acteur_cabinet(request.auth))
    return intervenant, code


@router.get("/projets/{projet_id}/ged")
def etat(request, projet_id: int):
    return _etat(get_object_or_404(Projet, pk=projet_id), request)


@router.post("/projets/{projet_id}/ged", response={201: dict})
def ouvrir(request, projet_id: int, donnees: OuvertureIn):
    projet = get_object_or_404(Projet, pk=projet_id)
    with transaction.atomic():
        espace, cree = EspaceChantier.objects.get_or_create(projet=projet, defaults={
            "ouvert_par": request.auth, "emails_moe": request.auth.email or "",
        })
        if not cree:
            raise HttpError(409, "L'espace de ce chantier est déjà ouvert.")
        journaliser(espace, TypeEvenement.ESPACE, "Espace documentaire du chantier ouvert", acteur_cabinet(request.auth))
        codes = []
        for intervenant_in in donnees.intervenants:
            intervenant, code = _creer_intervenant(espace, intervenant_in, request)
            codes.append({"intervenant_id": intervenant.pk, "nom": intervenant.nom, "code": code})
    return 201, {**_etat(projet, request), "codes": codes}


@router.patch("/ged/espaces/{espace_id}")
def parametrer(request, espace_id: int, donnees: EspaceIn):
    espace = _espace(espace_id)
    champs = donnees.model_dump(exclude_unset=True)
    for champ in ("notifications", "message_accueil", "delai_visa_jours"):
        if champs.get(champ) is not None:
            setattr(espace, champ, champs[champ])
    if champs.get("emails_moe") is not None:
        espace.emails_moe = _emails(champs["emails_moe"])
    espace.save()
    return _etat(espace.projet, request)


@router.post("/ged/espaces/{espace_id}/intervenants", response={201: dict})
def ajouter_intervenant(request, espace_id: int, donnees: IntervenantIn):
    espace = _espace(espace_id)
    if espace.statut != StatutEspace.OUVERT:
        raise HttpError(409, "L'espace de ce chantier est clos.")
    with transaction.atomic():
        intervenant, code = _creer_intervenant(espace, donnees, request)
    return 201, {"intervenant": intervenant_out(intervenant), "code": code}


def _intervenant(intervenant_id: int) -> Intervenant:
    return get_object_or_404(Intervenant.objects.select_related("espace__projet").prefetch_related("lots"), pk=intervenant_id)


@router.patch("/ged/intervenants/{intervenant_id}")
def modifier_intervenant(request, intervenant_id: int, donnees: ModificationIntervenant):
    intervenant = _intervenant(intervenant_id)
    champs = donnees.model_dump(exclude_unset=True)
    for champ in ("nom", "profil", "notifications", "actif"):
        if champs.get(champ) is not None:
            setattr(intervenant, champ, champs[champ].strip() if champ == "nom" else champs[champ])
    if champs.get("emails") is not None:
        intervenant.emails = _emails(champs["emails"])
    if champs.get("lot_ids") is not None:
        lots = list(intervenant.espace.projet.lots.filter(pk__in=champs["lot_ids"]))
        if len(lots) != len(set(champs["lot_ids"])):
            raise HttpError(400, "Lot inconnu pour ce chantier.")
        intervenant.lots.set(lots)
    if intervenant.profil == Profil.ENTREPRISE and not intervenant.lots.exists():
        raise HttpError(400, "Choisissez au moins un lot pour une entreprise.")
    intervenant.save()
    if "actif" in champs or "lot_ids" in champs or "profil" in champs:
        etat_acces = "désactivé" if not intervenant.actif else "modifié"
        journaliser(intervenant.espace, TypeEvenement.ACCES, f"Accès de {intervenant.nom} {etat_acces}", acteur_cabinet(request.auth))
    return intervenant_out(intervenant)


def message_invitation(intervenant: Intervenant, code: str) -> tuple[str, str]:
    projet = intervenant.espace.projet
    lien = (settings.GED_URL_PUBLIQUE or settings.URL_APPLICATION).rstrip("/") + "/ged"
    lots = ", ".join(f"lot {l.code} – {l.intitule}" for l in intervenant.lots.all())
    objet = f"{projet.nom} – accès à l'espace documentaire du chantier"
    corps = f"""Madame, Monsieur,

L'espace documentaire du chantier « {projet.nom} » est ouvert{f" pour : {lots}" if lots else ""}.
Vous y trouverez les plans et documents à jour, et vous y déposerez vos documents d'exécution (plans, fiches techniques, notes de calcul) soumis au visa de la maîtrise d'œuvre. Chaque nouveau document ou nouvel indice vous est signalé par courriel.

Adresse : {lien}
Votre code d'accès : {code}

Ce code est personnel à votre {"entreprise" if intervenant.profil == Profil.ENTREPRISE else "organisme"} : ne le communiquez qu'aux personnes qui suivent ce chantier. En cas de perte, demandez-nous un nouveau code (l'ancien cessera alors de fonctionner).

Bien cordialement,

{projet.maitre_oeuvre or "La maîtrise d'œuvre"}"""
    return objet, corps


@router.post("/ged/intervenants/{intervenant_id}/code")
def nouveau_code(request, intervenant_id: int, donnees: CodeIn):
    """Nouveau code (l'ancien est révoqué) ; envoi de l'invitation si la messagerie est configurée."""
    intervenant = _intervenant(intervenant_id)
    if not intervenant.actif:
        raise HttpError(400, "Réactivez d'abord l'accès de cet intervenant.")
    code = attribuer_code(intervenant)
    objet, corps = message_invitation(intervenant, code)
    envoye = False
    if donnees.envoyer:
        destinataires = intervenant.liste_emails()
        if not destinataires:
            raise HttpError(400, "Aucune adresse e-mail pour cet intervenant : ajoutez-en une ou remettez le code vous-même.")
        if settings.EMAIL_ACTIF:
            try:
                EmailMessage(objet, corps, settings.DEFAULT_FROM_EMAIL, destinataires).send()
            except Exception as erreur:  # noqa: BLE001
                raise HttpError(502, f"Envoi impossible ({erreur.__class__.__name__}) : le nouveau code est affiché, remettez-le vous-même.") from None
            envoye = True
    journaliser(intervenant.espace, TypeEvenement.ACCES, f"Nouveau code d'accès pour {intervenant.nom}" + (" envoyé par courriel" if envoye else ""), acteur_cabinet(request.auth))
    return {"intervenant": intervenant_out(intervenant), "code": code, "envoye": envoye, "objet": objet, "message": corps, "destinataires": intervenant.liste_emails()}


@router.get("/ged/espaces/{espace_id}/documents")
def documents(request, espace_id: int):
    return vues.lister(_espace(espace_id), acteur_cabinet(request.auth))


@router.post("/ged/espaces/{espace_id}/documents", response={201: dict})
def deposer(
    request, espace_id: int, fichier: File[UploadedFile], zone: Form[str], categorie: Form[str], lot_id: Form[int | None] = None,
    titre: Form[str] = "", reference: Form[str] = "", indice: Form[str] = "", objet: Form[str] = "", visa_requis: Form[bool] = False,
):
    espace = _espace(espace_id)
    return 201, vues.deposer_formulaire(acteur_cabinet(request.auth), espace, fichier, zone=zone, lot_id=lot_id, categorie=categorie, titre=titre,
                                        reference=reference, indice=indice, objet=objet, visa_requis=visa_requis)


@router.post("/ged/espaces/{espace_id}/documents/{document_id}/versions", response={201: dict})
def ajouter_indice(request, espace_id: int, document_id: int, fichier: File[UploadedFile], indice: Form[str] = "", objet: Form[str] = "",
                   visa_requis: Form[bool | None] = None):
    return 201, vues.nouvel_indice_formulaire(acteur_cabinet(request.auth), _espace(espace_id), document_id, fichier, indice=indice, objet=objet, visa_requis=visa_requis)


@router.patch("/ged/espaces/{espace_id}/documents/{document_id}")
def modifier_document(request, espace_id: int, document_id: int, donnees: ModificationDocument):
    espace = _espace(espace_id)
    acteur = acteur_cabinet(request.auth)
    document = vues.document_visible(acteur, espace, document_id)
    champs = donnees.model_dump(exclude_unset=True)
    if champs.get("annule") is True and not document.annule:
        annuler(acteur, document, champs.get("motif_annulation") or "")
    elif champs.get("annule") is False and document.annule:
        retablir(acteur, document)
    modifies = []
    for champ in ("titre", "reference", "categorie"):
        valeur = (champs.get(champ) or "").strip()
        if valeur and valeur != getattr(document, champ):
            if champ == "categorie" and valeur not in dict(Document._meta.get_field("categorie").choices):
                raise HttpError(400, "Catégorie inconnue.")
            if champ == "reference" and Document.objects.filter(espace=espace, reference=valeur).exclude(pk=document.pk).exists():
                raise HttpError(409, f"La référence « {valeur} » existe déjà dans cet espace.")
            setattr(document, champ, valeur)
            modifies.append(champ)
    if modifies:
        document.save(update_fields=modifies)
        journaliser(espace, TypeEvenement.MODIFICATION, f"{document.reference} – {document.titre} : {', '.join(modifies)} modifié(s)", acteur, document=document)
    return document_out(Document.objects.select_related("lot", "espace").prefetch_related("versions").get(pk=document.pk), acteur)


@router.post("/ged/espaces/{espace_id}/versions/{version_id}/visa")
def viser(request, espace_id: int, version_id: int, statut: Form[str], commentaire: Form[str] = "", fichier: File[UploadedFile | None] = None):
    return vues.viser_formulaire(acteur_cabinet(request.auth), _espace(espace_id), version_id, statut=statut, commentaire=commentaire, fichier=fichier)


@router.get("/ged/espaces/{espace_id}/versions/{version_id}/fichier")
def fichier(request, espace_id: int, version_id: int):
    return vues.telecharger(acteur_cabinet(request.auth), _espace(espace_id), version_id)


@router.get("/ged/espaces/{espace_id}/versions/{version_id}/visa")
def fichier_visa(request, espace_id: int, version_id: int):
    return vues.telecharger(acteur_cabinet(request.auth), _espace(espace_id), version_id, visa=True)


@router.get("/ged/espaces/{espace_id}/journal")
def journal(request, espace_id: int, page: int = 1):
    return vues.journal(_espace(espace_id), acteur_cabinet(request.auth), page)


@router.get("/ged/espaces/{espace_id}/registre.xlsx")
def registre(request, espace_id: int):
    return vues.registre_xlsx(_espace(espace_id), acteur_cabinet(request.auth))
