"""API de la GED côté cabinet (comptes Administrateur et Maîtrise d'œuvre)."""
from __future__ import annotations

import datetime
from typing import Literal

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
from .acces import adresse_ip, navigateur, nouveau_code
from .categories import PAR_CODE
from .droits import acteur_cabinet
from .models import Acces, Document, EspaceChantier, Frequence, Intervenant, Profil, StatutEspace, TypeEvenement
from .serialisation import acces_out, document_out, droits_out, intervenant_out, referentiels
from .services import annuler, journaliser, retablir

router = Router(tags=["GED de chantier"])


class PersonneIn(Schema):
    nom: str = Field(..., max_length=255)
    email: str = Field("", max_length=254)
    frequence: Frequence | None = None


class IntervenantIn(Schema):
    entreprise_id: int | None = None
    nom: str = Field("", max_length=255)
    profil: Profil = Profil.ENTREPRISE
    lot_ids: list[int] = []
    personnes: list[PersonneIn] = []
    sous_traitant_de: int | None = None


class OuvertureIn(Schema):
    intervenants: list[IntervenantIn] = []
    importer_dce: bool = True


class EspaceIn(Schema):
    notifications: bool | None = None
    emails_moe: list[str] | None = None
    message_accueil: str | None = Field(None, max_length=4000)
    delai_visa_jours: int | None = Field(None, ge=1, le=90)
    lecture_inter_lots: bool | None = None
    statut: StatutEspace | None = None
    date_reception: datetime.date | None = None


class ModificationIntervenant(Schema):
    nom: str | None = Field(None, max_length=255)
    profil: Profil | None = None
    lot_ids: list[int] | None = None
    actif: bool | None = None
    voit_confidentielles: bool | None = None


class ModificationAcces(Schema):
    nom: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=254)
    frequence: Frequence | None = None
    actif: bool | None = None


class CodeIn(Schema):
    envoyer: bool = False


class ModificationDocument(Schema):
    titre: str | None = Field(None, max_length=255)
    reference: str | None = Field(None, max_length=60)
    reference_emetteur: str | None = Field(None, max_length=80)
    categorie: str | None = None
    annule: bool | None = None
    motif_annulation: str | None = Field(None, max_length=500)


def _espace(espace_id: int) -> EspaceChantier:
    return get_object_or_404(EspaceChantier.objects.select_related("projet"), pk=espace_id)


def _email(adresse: str) -> str:
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    adresse = (adresse or "").strip()
    if adresse:
        try:
            validate_email(adresse)
        except ValidationError:
            raise HttpError(400, f"Adresse e-mail invalide : {adresse}") from None
    return adresse


def _emails(liste: list[str]) -> str:
    return "\n".join(dict.fromkeys(a for a in (_email(x) for x in liste) if a))


def _acteur(request):
    return acteur_cabinet(request.auth, adresse_ip(request), navigateur(request))


def _suggestions(projet: Projet, espace: EspaceChantier | None) -> list[dict]:
    """Entreprises retenues à l'analyse des offres, avec leurs lots et contacts, pas encore intervenantes."""
    deja = set(espace.intervenants.exclude(entreprise=None).values_list("entreprise_id", flat=True)) if espace else set()
    par_entreprise: dict[int, dict] = {}
    for c in ConsultationEntreprise.objects.filter(projet=projet, statut=StatutConsultation.RETENUE).select_related("entreprise", "lot").prefetch_related("entreprise__contacts"):
        if c.entreprise_id in deja:
            continue
        entreprise = c.entreprise
        contacts = [{"nom": x.nom, "email": x.email} for x in entreprise.contacts.all() if x.email]
        fiche = par_entreprise.setdefault(c.entreprise_id, {
            "entreprise_id": c.entreprise_id, "nom": entreprise.raison_sociale, "lots": [],
            "personnes": contacts[:3] or ([{"nom": entreprise.raison_sociale, "email": entreprise.email}] if entreprise.email else []),
        })
        fiche["lots"].append({"id": c.lot_id, "code": c.lot.code, "intitule": c.lot.intitule})
    return sorted(par_entreprise.values(), key=lambda f: f["nom"])


def _espace_out(espace: EspaceChantier, request) -> dict:
    from django.utils import timezone

    from .models import Diffusion, Notification, StatutVisa, Version

    acteur = _acteur(request)
    attente = Version.objects.filter(document__espace=espace, document__annule=False, diffusion=Diffusion.POUR_VISA, visa=StatutVisa.EN_ATTENTE)
    lots_sans_entreprise = [
        {"id": l.pk, "code": l.code, "intitule": l.intitule}
        for l in espace.projet.lots.order_by("ordre", "code")
        if not espace.intervenants.filter(profil=Profil.ENTREPRISE, actif=True, lots=l).exists()
    ]
    return {
        "id": espace.pk, "statut": espace.statut, "statut_libelle": espace.get_statut_display(), "ouvert_le": espace.ouvert_le,
        "notifications": espace.notifications, "emails_moe": espace.liste_emails_moe(), "message_accueil": espace.message_accueil,
        "delai_visa_jours": espace.delai_visa_jours, "lecture_inter_lots": espace.lecture_inter_lots, "date_reception": espace.date_reception,
        "intervenants": [intervenant_out(i) for i in espace.intervenants.prefetch_related("lots", "acces")],
        "lots_sans_entreprise": lots_sans_entreprise,
        "droits": droits_out(acteur, espace),
        "statistiques": {
            "documents": espace.documents.count(), "en_attente_visa": attente.count(),
            "visas_en_retard": attente.filter(echeance_visa__lt=timezone.localdate()).count(),
            "notifications_en_echec": Notification.objects.filter(evenement__espace=espace, envoyee_le__isnull=True).count(),
        },
    }


def _etat(projet: Projet, request) -> dict:
    espace = EspaceChantier.objects.filter(projet=projet).first()
    return {
        "projet": {"id": projet.pk, "nom": projet.nom, "type_marche": projet.type_marche, "maitre_ouvrage": projet.maitre_ouvrage},
        "espace": _espace_out(espace, request) if espace else None,
        "suggestions": _suggestions(projet, espace),
        "email_actif": settings.EMAIL_ACTIF,
        "url_publique": settings.GED_URL_PUBLIQUE,
        **referentiels(),
    }


def _frequence_defaut(profil: str) -> str:
    # Entreprises et maîtrise d'œuvre associée : à chaque nouveauté ; MOA, CT, CSPS, OPC : récapitulatif quotidien.
    return Frequence.IMMEDIATE if profil in (Profil.ENTREPRISE, Profil.MOE_EXTERNE) else Frequence.QUOTIDIENNE


def _creer_acces(intervenant: Intervenant, personne: PersonneIn) -> tuple[Acces, str]:
    acces = Acces(
        intervenant=intervenant, nom=(personne.nom or intervenant.nom).strip()[:255], email=_email(personne.email),
        frequence=personne.frequence or _frequence_defaut(intervenant.profil),
    )
    code = nouveau_code(acces)
    acces.save()
    return acces, code


def _creer_intervenant(espace: EspaceChantier, donnees: IntervenantIn, request) -> tuple[Intervenant, list[dict]]:
    entreprise = get_object_or_404(Entreprise, pk=donnees.entreprise_id) if donnees.entreprise_id else None
    nom = (donnees.nom or (entreprise.raison_sociale if entreprise else "")).strip()
    if not nom:
        raise HttpError(400, "Indiquez le nom de l'intervenant.")
    lots = list(espace.projet.lots.filter(pk__in=donnees.lot_ids))
    if len(lots) != len(set(donnees.lot_ids)):
        raise HttpError(400, "Lot inconnu pour ce chantier.")
    if donnees.profil == Profil.ENTREPRISE and not lots:
        raise HttpError(400, f"Choisissez au moins un lot pour {nom}.")
    titulaire = None
    if donnees.sous_traitant_de:
        titulaire = get_object_or_404(Intervenant, pk=donnees.sous_traitant_de, espace=espace, profil=Profil.ENTREPRISE)
    intervenant = Intervenant.objects.create(
        espace=espace, entreprise=entreprise, nom=nom[:255], profil=donnees.profil, sous_traitant_de=titulaire,
        voit_confidentielles=titulaire is None,  # un sous-traitant (DC4) ne voit pas les pièces chiffrées du titulaire
    )
    intervenant.lots.set(lots)
    personnes = donnees.personnes or [PersonneIn(nom=nom, email=entreprise.email if entreprise else "")]
    invitations = []
    for personne in personnes:
        acces, code = _creer_acces(intervenant, personne)
        invitations.append({"acces_id": acces.pk, "intervenant": intervenant.nom, **_invitation(acces, code)})
    journaliser(espace, TypeEvenement.ACCES, f"Accès ouvert pour {intervenant.nom} ({intervenant.get_profil_display()}, {len(personnes)} personne(s))", _acteur(request))
    return intervenant, invitations


def _importer_dce(espace: EspaceChantier, request) -> int:
    """Plans et documents du DCE repris en « Pièces du marché », à l'indice 0."""
    from django.core.files.base import File as FichierDjango

    from dce.models import PieceJointe

    from .services import deposer as deposer_document

    acteur = _acteur(request)
    nombre = 0
    for jointe in PieceJointe.objects.filter(projet=espace.projet).select_related("lot"):
        try:
            with jointe.fichier.open("rb") as flux:
                fichier = FichierDjango(flux, name=jointe.nom_original)
                fichier.size = jointe.taille
                deposer_document(acteur, espace, zone="LOT" if jointe.lot_id else "COMMUN", lot=jointe.lot, categorie="MAR", titre=jointe.titre,
                                 fichier=fichier, indice="0", objet="Pièce du marché (DCE)", diffusion="BPE" if jointe.categorie == "PLANS" else "INFO")
            nombre += 1
        except (FileNotFoundError, HttpError):
            continue
    return nombre


@router.get("/projets/{projet_id}/ged")
def etat(request, projet_id: int):
    return _etat(get_object_or_404(Projet, pk=projet_id), request)


@router.post("/projets/{projet_id}/ged", response={201: dict})
def ouvrir(request, projet_id: int, donnees: OuvertureIn):
    projet = get_object_or_404(Projet, pk=projet_id)
    with transaction.atomic():
        espace, cree = EspaceChantier.objects.get_or_create(projet=projet, defaults={
            "ouvert_par": request.auth, "emails_moe": request.auth.email or "",
            "message_accueil": f"Bienvenue sur l'espace documentaire du chantier « {projet.nom} ». Déposez ici vos documents d'exécution ; "
                               "utilisez toujours l'indice indiqué « À utiliser ».",
        })
        if not cree:
            raise HttpError(409, "L'espace de ce chantier est déjà ouvert.")
        journaliser(espace, TypeEvenement.ESPACE, "Espace documentaire du chantier ouvert", _acteur(request))
        invitations = []
        for intervenant_in in donnees.intervenants:
            invitations += _creer_intervenant(espace, intervenant_in, request)[1]
        importes = _importer_dce(espace, request) if donnees.importer_dce else 0
    # Les codes ne sont affichés qu'ici (et à chaque nouvelle invitation) : à envoyer ou imprimer.
    return 201, {**_etat(projet, request), "documents_importes": importes, "invitations": invitations}


@router.patch("/ged/espaces/{espace_id}")
def parametrer(request, espace_id: int, donnees: EspaceIn):
    espace = _espace(espace_id)
    champs = donnees.model_dump(exclude_unset=True)
    for champ in ("notifications", "message_accueil", "delai_visa_jours", "lecture_inter_lots"):
        if champs.get(champ) is not None:
            setattr(espace, champ, champs[champ])
    if champs.get("emails_moe") is not None:
        espace.emails_moe = _emails(champs["emails_moe"])
    if "date_reception" in champs:
        espace.date_reception = champs["date_reception"]
    if champs.get("statut") is not None and champs["statut"] != espace.statut:
        if champs["statut"] == StatutEspace.RECEPTION and not espace.date_reception:
            raise HttpError(400, "Indiquez la date de réception des travaux.")
        espace.statut = champs["statut"]
        journaliser(espace, TypeEvenement.ESPACE, f"Espace : {espace.get_statut_display().lower()}", _acteur(request))
    espace.save()
    return _etat(espace.projet, request)


@router.post("/ged/espaces/{espace_id}/intervenants", response={201: dict})
def ajouter_intervenant(request, espace_id: int, donnees: IntervenantIn):
    espace = _espace(espace_id)
    if espace.statut == StatutEspace.CLOS:
        raise HttpError(409, "L'espace de ce chantier est clos.")
    with transaction.atomic():
        intervenant, invitations = _creer_intervenant(espace, donnees, request)
    return 201, {"intervenant": intervenant_out(Intervenant.objects.prefetch_related("lots", "acces").get(pk=intervenant.pk)), "invitations": invitations}


def _intervenant(intervenant_id: int) -> Intervenant:
    return get_object_or_404(Intervenant.objects.select_related("espace__projet").prefetch_related("lots", "acces"), pk=intervenant_id)


@router.patch("/ged/intervenants/{intervenant_id}")
def modifier_intervenant(request, intervenant_id: int, donnees: ModificationIntervenant):
    intervenant = _intervenant(intervenant_id)
    champs = donnees.model_dump(exclude_unset=True)
    for champ in ("nom", "profil", "actif", "voit_confidentielles"):
        if champs.get(champ) is not None:
            setattr(intervenant, champ, champs[champ].strip() if champ == "nom" else champs[champ])
    if champs.get("lot_ids") is not None:
        lots = list(intervenant.espace.projet.lots.filter(pk__in=champs["lot_ids"]))
        if len(lots) != len(set(champs["lot_ids"])):
            raise HttpError(400, "Lot inconnu pour ce chantier.")
        intervenant.lots.set(lots)
    if intervenant.profil == Profil.ENTREPRISE and not intervenant.lots.exists():
        raise HttpError(400, "Choisissez au moins un lot pour une entreprise.")
    intervenant.save()
    if {"actif", "lot_ids", "profil"} & champs.keys():
        etat_acces = "désactivé" if not intervenant.actif else "modifié"
        journaliser(intervenant.espace, TypeEvenement.ACCES, f"Accès de {intervenant.nom} {etat_acces}", _acteur(request))
    return intervenant_out(Intervenant.objects.prefetch_related("lots", "acces").get(pk=intervenant.pk))


@router.post("/ged/intervenants/{intervenant_id}/acces", response={201: dict})
def ajouter_acces(request, intervenant_id: int, donnees: PersonneIn):
    intervenant = _intervenant(intervenant_id)
    acces, code = _creer_acces(intervenant, donnees)
    journaliser(intervenant.espace, TypeEvenement.ACCES, f"Accès personnel créé : {acces.nom} ({intervenant.nom})", _acteur(request))
    return 201, {"acces": acces_out(acces), "acces_id": acces.pk, "intervenant": intervenant.nom, **_invitation(acces, code)}


def _acces(acces_id: int) -> Acces:
    return get_object_or_404(Acces.objects.select_related("intervenant__espace__projet").prefetch_related("intervenant__lots"), pk=acces_id)


@router.patch("/ged/acces/{acces_id}")
def modifier_acces(request, acces_id: int, donnees: ModificationAcces):
    acces = _acces(acces_id)
    champs = donnees.model_dump(exclude_unset=True)
    if champs.get("nom"):
        acces.nom = champs["nom"].strip()[:255]
    if champs.get("email") is not None:
        acces.email = _email(champs["email"])
    for champ in ("frequence", "actif"):
        if champs.get(champ) is not None:
            setattr(acces, champ, champs[champ])
    acces.save()
    if "actif" in champs:
        journaliser(acces.intervenant.espace, TypeEvenement.ACCES, f"Accès de {acces.nom} ({acces.intervenant.nom}) {'réactivé' if acces.actif else 'désactivé'}", _acteur(request))
    return acces_out(acces)


def lien_portail() -> str:
    return (settings.GED_URL_PUBLIQUE or settings.URL_APPLICATION).rstrip("/") + "/ged"


def message_invitation(acces: Acces, code: str) -> tuple[str, str]:
    intervenant = acces.intervenant
    projet = intervenant.espace.projet
    lots = ", ".join(f"lot {l.code} – {l.intitule}" for l in intervenant.lots.all())
    objet = f"{projet.nom} – votre accès à l'espace documentaire du chantier"
    corps = f"""Bonjour {acces.nom},

L'espace documentaire du chantier « {projet.nom} » est ouvert{f" pour {intervenant.nom} ({lots})" if lots else f" pour {intervenant.nom}"}.
Vous y trouverez les plans et documents à jour (utilisez toujours l'indice marqué « À utiliser »){", et vous y déposerez vos documents d'exécution (plans, fiches techniques, notes de calcul) soumis au visa de la maîtrise d'œuvre" if intervenant.profil == Profil.ENTREPRISE else ""}. Chaque nouveauté vous est signalée par courriel.

Accès direct : {lien_portail()}#code={code}
Adresse : {lien_portail()}
Votre code personnel : {code}

Ce code est personnel : ne le communiquez pas. Vos collègues peuvent recevoir leur propre accès sur simple demande.

Bien cordialement,

{projet.maitre_oeuvre or "La maîtrise d'œuvre"}"""
    return objet, corps


def _invitation(acces: Acces, code: str) -> dict:
    objet, corps = message_invitation(acces, code)
    return {"code": code, "objet": objet, "message": corps, "lien": f"{lien_portail()}#code={code}", "destinataire": acces.email, "nom": acces.nom}


@router.post("/ged/acces/{acces_id}/invitation")
def inviter(request, acces_id: int, donnees: CodeIn):
    """Nouveau code pour cette personne seulement (l'ancien cesse de fonctionner), envoyé si demandé.

    Le code n'étant jamais conservé en clair, renvoyer une invitation en génère toujours un nouveau.
    """
    acces = _acces(acces_id)
    if not (acces.actif and acces.intervenant.actif):
        raise HttpError(400, "Réactivez d'abord cet accès.")
    if donnees.envoyer and not acces.email:
        raise HttpError(400, "Aucune adresse e-mail pour cette personne : ajoutez-en une ou remettez-lui sa fiche d'accès.")
    code = nouveau_code(acces)
    acces.save(update_fields=["code_empreinte", "code_fin", "code_genere_le"])
    resultat = {"acces": acces_out(acces), "acces_id": acces.pk, "intervenant": acces.intervenant.nom, **_invitation(acces, code), "envoye": False}
    if donnees.envoyer and settings.EMAIL_ACTIF:
        try:
            EmailMessage(resultat["objet"], resultat["message"], settings.DEFAULT_FROM_EMAIL, [acces.email]).send()
            resultat["envoye"] = True
        except Exception as erreur:  # noqa: BLE001
            resultat["erreur_envoi"] = f"Envoi impossible ({erreur.__class__.__name__}) : remettez le code vous-même."
    journaliser(acces.intervenant.espace, TypeEvenement.ACCES, f"Nouveau code pour {acces.nom} ({acces.intervenant.nom})" + (" envoyé par courriel" if resultat["envoye"] else ""), _acteur(request))
    return resultat


@router.get("/ged/espaces/{espace_id}/documents")
def documents(request, espace_id: int):
    return vues.lister(_espace(espace_id), _acteur(request))


@router.post("/ged/espaces/{espace_id}/documents", response={201: dict})
def deposer(
    request, espace_id: int, fichier: File[UploadedFile], zone: Form[str], categorie: Form[str], lot_id: Form[int | None] = None,
    titre: Form[str] = "", reference: Form[str] = "", reference_emetteur: Form[str] = "", indice: Form[str] = "", objet: Form[str] = "",
    diffusion: Form[str] = "", date_indice: Form[datetime.date | None] = None, depot: Form[str] = "",
    sources: File[list[UploadedFile]] = None,
):
    espace = _espace(espace_id)
    return 201, vues.deposer_formulaire(_acteur(request), espace, fichier, zone=zone, lot_id=lot_id, categorie=categorie, titre=titre,
                                        reference=reference, reference_emetteur=reference_emetteur, indice=indice, objet=objet,
                                        diffusion=diffusion, date_indice=date_indice, sources=sources, depot=depot)


@router.post("/ged/espaces/{espace_id}/documents/{document_id}/versions", response={201: dict})
def ajouter_indice(request, espace_id: int, document_id: int, fichier: File[UploadedFile], indice: Form[str] = "", objet: Form[str] = "",
                   diffusion: Form[str] = "", date_indice: Form[datetime.date | None] = None, depot: Form[str] = "",
                   sources: File[list[UploadedFile]] = None, forcer: Form[str] = ""):
    return 201, vues.nouvel_indice_formulaire(_acteur(request), _espace(espace_id), document_id, fichier, indice=indice, objet=objet,
                                              diffusion=diffusion, date_indice=date_indice, sources=sources, depot=depot, forcer=forcer)


@router.patch("/ged/espaces/{espace_id}/documents/{document_id}")
def modifier_document(request, espace_id: int, document_id: int, donnees: ModificationDocument):
    espace = _espace(espace_id)
    acteur = _acteur(request)
    document = vues.document_visible(acteur, espace, document_id)
    champs = donnees.model_dump(exclude_unset=True)
    if champs.get("annule") is True and not document.annule:
        annuler(acteur, document, champs.get("motif_annulation") or "")
    elif champs.get("annule") is False and document.annule:
        retablir(acteur, document)
    modifies = []
    for champ in ("titre", "reference", "reference_emetteur", "categorie"):
        valeur = (champs.get(champ) or "").strip()
        if (valeur or champ == "reference_emetteur" and champ in champs) and valeur != getattr(document, champ):
            if champ == "categorie" and valeur not in PAR_CODE:
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
def viser(request, espace_id: int, version_id: int, statut: Form[str], commentaire: Form[str] = "", fichier: File[UploadedFile | None] = None,
          nouvel_indice_attendu: Form[bool | None] = None):
    return vues.viser_formulaire(_acteur(request), _espace(espace_id), version_id, statut=statut, commentaire=commentaire, fichier=fichier,
                                 nouvel_indice_attendu=nouvel_indice_attendu)


@router.get("/ged/espaces/{espace_id}/versions/{version_id}/{quoi}")
def fichier(request, espace_id: int, version_id: int, quoi: Literal["fichier", "annote", "fiche"]):
    return vues.telecharger(_acteur(request), _espace(espace_id), version_id, quoi=quoi)


@router.get("/ged/espaces/{espace_id}/sources/{source_id}")
def fichier_source(request, espace_id: int, source_id: int):
    return vues.telecharger_source(_acteur(request), _espace(espace_id), source_id)


@router.get("/ged/espaces/{espace_id}/avis/{avis_id}/fichier")
def fichier_avis(request, espace_id: int, avis_id: int):
    return vues.telecharger_avis(_acteur(request), _espace(espace_id), avis_id)


@router.get("/ged/espaces/{espace_id}/journal")
def journal(request, espace_id: int, page: int = 1):
    return vues.journal(_espace(espace_id), _acteur(request), page)


@router.get("/ged/espaces/{espace_id}/registre.xlsx")
def registre(request, espace_id: int):
    return vues.registre_xlsx(_espace(espace_id), _acteur(request))
