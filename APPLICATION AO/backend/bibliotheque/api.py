import hashlib
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from referentiel.api import LotOut
from referentiel.models import Lot

from .extraction import EXTENSIONS_ACCEPTEES
from .models import TYPES_PAR_LOT, DocumentReference, TypeDocument, TypeMarche
from .tasks import analyser_document

router = Router(tags=["Bibliothèque documentaire"])


class DocumentOut(Schema):
    id: int
    type_document: str
    type_document_libelle: str
    lot: LotOut | None
    nom_original: str
    taille: int
    operation: str
    annee: int | None
    type_marche: str
    type_marche_libelle: str
    statut_analyse: str
    statut_analyse_libelle: str
    message_analyse: str
    ajoute_le: datetime
    ajoute_par: str | None

    @staticmethod
    def resolve_type_document_libelle(obj):
        return obj.get_type_document_display()

    @staticmethod
    def resolve_type_marche_libelle(obj):
        return obj.get_type_marche_display() if obj.type_marche else ""

    @staticmethod
    def resolve_statut_analyse_libelle(obj):
        return obj.get_statut_analyse_display()

    @staticmethod
    def resolve_ajoute_par(obj):
        if obj.ajoute_par is None:
            return None
        return obj.ajoute_par.get_full_name() or obj.ajoute_par.username


class DocumentIn(Schema):
    type_document: TypeDocument
    lot_id: int | None = None
    operation: str = ""
    annee: int | None = None
    type_marche: TypeMarche | None = None


class StatistiquesOut(Schema):
    total: int
    par_type: dict[str, int]
    par_lot: dict[str, dict[str, int]]


def _champs_liste():
    return (
        DocumentReference.objects.select_related("lot", "ajoute_par")
        .defer("texte_extrait")
    )


@router.get("/documents", response=list[DocumentOut])
def lister_documents(
    request,
    type_document: TypeDocument | None = None,
    lot_id: int | None = None,
    recherche: str = "",
):
    documents = _champs_liste()
    if type_document:
        documents = documents.filter(type_document=type_document)
    if lot_id:
        documents = documents.filter(lot_id=lot_id)
    recherche = recherche.strip()
    if recherche:
        documents = documents.filter(
            Q(nom_original__icontains=recherche) | Q(operation__icontains=recherche)
        )
    return documents


@router.post("/documents", response={201: DocumentOut})
def ajouter_document(request, fichier: File[UploadedFile], donnees: Form[DocumentIn]):
    extension = Path(fichier.name or "").suffix.lower()
    if extension not in EXTENSIONS_ACCEPTEES:
        formats = ", ".join(sorted(EXTENSIONS_ACCEPTEES))
        raise HttpError(400, f"Format « {extension or 'inconnu'} » non accepté. Formats possibles : {formats}.")

    taille_max = settings.TAILLE_MAX_FICHIER_MO * 1024 * 1024
    if fichier.size > taille_max:
        raise HttpError(400, f"Fichier trop volumineux (maximum {settings.TAILLE_MAX_FICHIER_MO} Mo).")
    if fichier.size == 0:
        raise HttpError(400, "Le fichier est vide.")

    lot = None
    if donnees.type_document in TYPES_PAR_LOT:
        if donnees.lot_id is None:
            raise HttpError(400, "Choisissez le lot auquel appartient ce document.")
        lot = Lot.objects.filter(pk=donnees.lot_id, actif=True).first()
        if lot is None:
            raise HttpError(400, "Ce lot n'existe pas ou n'est plus actif.")
    elif donnees.lot_id is not None:
        raise HttpError(400, "Ce type de document n'est pas classé par lot.")

    annee_max = timezone.now().year + 1
    if donnees.annee is not None and not 1950 <= donnees.annee <= annee_max:
        raise HttpError(400, f"L'année doit être comprise entre 1950 et {annee_max}.")

    empreinte = hashlib.sha256()
    for morceau in fichier.chunks():
        empreinte.update(morceau)
    empreinte = empreinte.hexdigest()
    fichier.seek(0)

    doublon = DocumentReference.objects.filter(
        type_document=donnees.type_document, empreinte_sha256=empreinte
    ).first()
    if doublon is not None:
        raise HttpError(409, _message_doublon(doublon))

    try:
        with transaction.atomic():
            document = DocumentReference.objects.create(
                type_document=donnees.type_document,
                lot=lot,
                fichier=fichier,
                nom_original=(fichier.name or "document")[:255],
                taille=fichier.size,
                empreinte_sha256=empreinte,
                operation=donnees.operation.strip()[:255],
                annee=donnees.annee,
                type_marche=donnees.type_marche or "",
                ajoute_par=request.auth,
            )
    except IntegrityError:
        doublon = DocumentReference.objects.get(
            type_document=donnees.type_document, empreinte_sha256=empreinte
        )
        raise HttpError(409, _message_doublon(doublon)) from None

    transaction.on_commit(lambda: analyser_document.delay(document.pk))
    return 201, _champs_liste().get(pk=document.pk)


def _message_doublon(doublon: DocumentReference) -> str:
    date = timezone.localtime(doublon.ajoute_le).strftime("%d/%m/%Y")
    return f"Déjà présent dans la bibliothèque : « {doublon.nom_original} », ajouté le {date}."


@router.get("/documents/{document_id}/telecharger")
def telecharger_document(request, document_id: int):
    document = get_object_or_404(DocumentReference, pk=document_id)
    return FileResponse(
        document.fichier.open("rb"), as_attachment=True, filename=document.nom_original
    )


@router.delete("/documents/{document_id}", response={204: None})
def supprimer_document(request, document_id: int):
    document = get_object_or_404(DocumentReference, pk=document_id)
    document.delete()
    return 204, None


@router.get("/statistiques", response=StatistiquesOut)
def statistiques(request):
    par_type = {code: 0 for code in TypeDocument.values}
    for ligne in DocumentReference.objects.values("type_document").annotate(n=Count("id")):
        par_type[ligne["type_document"]] = ligne["n"]

    par_lot: dict[str, dict[str, int]] = {code: {} for code in sorted(TYPES_PAR_LOT)}
    lignes = (
        DocumentReference.objects.filter(type_document__in=TYPES_PAR_LOT, lot__isnull=False)
        .values("type_document", "lot_id")
        .annotate(n=Count("id"))
    )
    for ligne in lignes:
        par_lot[ligne["type_document"]][str(ligne["lot_id"])] = ligne["n"]

    return {"total": sum(par_type.values()), "par_type": par_type, "par_lot": par_lot}
