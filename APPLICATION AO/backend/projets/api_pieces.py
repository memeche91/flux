"""API des pièces administratives (CCAP, RC, actes d'engagement) et de la consultation."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Literal

from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.http import content_disposition_header
from ninja import Field, Router, Schema
from ninja.errors import HttpError

from articles.models import Article
from bibliotheque.models import DocumentReference

from . import modeles as modeles_service
from . import ordre, pieces
from .champs import champs_du_projet, consultation_du_projet
from .exports.cctp_docx import exporter_docx
from .exports.document import nom_de_fichier
from .exports.pdf import exporter_pdf
from .html import nettoyer_html
from .models import Clause, FormePrix, GenreClause, LotProjet, ModelePiece, PieceEcrite, Projet, TypePiece, Visite

router = Router(tags=["Pièces administratives"])


# --- Schémas -----------------------------------------------------------------


class Critere(Schema):
    libelle: str = Field(..., min_length=1, max_length=255)
    ponderation: int = Field(..., ge=0, le=100)


class ConsultationSchema(Schema):
    date_limite_offres: datetime.datetime | None = None
    duree_validite_offres: int = Field(120, ge=0, le=3650)
    delai_execution: str = Field("", max_length=255)
    date_debut_travaux: str = Field("", max_length=100)
    visite: Visite = Visite.FACULTATIVE
    modalites_visite: str = Field("", max_length=255)
    variantes_autorisees: bool = False
    forme_prix: FormePrix = FormePrix.FERME_ACTUALISABLE
    index_reference: str = Field("BT01", max_length=50)
    taux_retenue_garantie: Decimal = Field(Decimal("5"), ge=0, le=100)
    taux_avance: Decimal = Field(Decimal("5"), ge=0, le=100)
    penalites_retard: str = Field("", max_length=255)
    profil_acheteur: str = Field("", max_length=255)
    contact: str = Field("", max_length=255)
    criteres: list[Critere] = Field(default_factory=list, max_length=12)


class ChampOut(Schema):
    cle: str
    libelle: str
    apercu: str
    renseigne: bool
    bloc: bool


class LotCourt(Schema):
    id: int
    code: str
    intitule: str


class PieceResume(Schema):
    id: int
    type_piece: str
    titre: str
    origine: str
    lot: LotCourt | None
    nb_clauses: int
    modifie_le: datetime.datetime


class ClauseOut(Schema):
    id: int
    genre: str
    numero: str
    titre: str
    contenu: str
    article_source_id: int | None


class ProjetPiece(Schema):
    id: int
    nom: str
    type_marche: str


class PieceDetail(Schema):
    id: int
    type_piece: str
    titre: str
    origine: str
    lot: LotCourt | None
    projet: ProjetPiece
    clauses: list[ClauseOut]


class ModeleOut(Schema):
    id: str
    nom: str
    type_piece: str
    marche: str
    origine: str
    nb_clauses: int


class CreationPiece(Schema):
    type_piece: TypePiece
    lot_id: int | None = None
    modele_id: str | None = None
    document_id: int | None = None


class CreationActes(Schema):
    modele_id: str | None = None


class PieceModification(Schema):
    titre: str = Field(..., min_length=1, max_length=255)


class ClauseIn(Schema):
    genre: GenreClause = GenreClause.ARTICLE
    titre: str = Field(..., min_length=1, max_length=500)
    contenu: str = ""
    apres_id: int | None = None


class ClauseModification(Schema):
    genre: GenreClause | None = None
    titre: str | None = Field(None, min_length=1, max_length=500)
    contenu: str | None = None


class Deplacement(Schema):
    sens: Literal["haut", "bas"]


class ImportDocument(Schema):
    document_id: int
    apres_id: int | None = None


class InsertionArticle(Schema):
    article_id: int
    apres_id: int | None = None


class NouveauModele(Schema):
    nom: str = Field(..., min_length=1, max_length=255)


# --- Outils --------------------------------------------------------------------


def _consultation_out(projet: Projet) -> dict:
    c = consultation_du_projet(projet)
    return {champ: getattr(c, champ) for champ in ConsultationSchema.model_fields}


def _piece(piece_id: int) -> PieceEcrite:
    return get_object_or_404(PieceEcrite.objects.select_related("projet", "lot"), pk=piece_id)


def _lot_court(lot: LotProjet | None) -> dict | None:
    return {"id": lot.pk, "code": lot.code, "intitule": lot.intitule} if lot else None


def _resume(piece: PieceEcrite) -> dict:
    return {
        "id": piece.pk,
        "type_piece": piece.type_piece,
        "titre": piece.titre,
        "origine": piece.origine,
        "lot": _lot_court(piece.lot),
        "nb_clauses": piece.clauses.count(),
        "modifie_le": piece.modifie_le,
    }


def _detail(piece: PieceEcrite) -> dict:
    clauses = pieces.clauses_ordonnees(piece)
    numeros = pieces.numeroter(clauses)
    return {
        "id": piece.pk,
        "type_piece": piece.type_piece,
        "titre": piece.titre,
        "origine": piece.origine,
        "lot": _lot_court(piece.lot),
        "projet": {"id": piece.projet_id, "nom": piece.projet.nom, "type_marche": piece.projet.type_marche},
        "clauses": [
            {
                "id": c.pk,
                "genre": c.genre,
                "numero": numeros[c.pk][0],
                "titre": c.titre,
                "contenu": c.contenu,
                "article_source_id": c.article_source_id,
            }
            for c in clauses
        ],
    }


def _toucher(piece: PieceEcrite) -> None:
    PieceEcrite.objects.filter(pk=piece.pk).update(modifie_le=timezone.now())


def _modele(identifiant: str | None) -> dict | None:
    if not identifiant:
        return None
    modele = modeles_service.obtenir_modele(identifiant)
    if modele is None:
        raise HttpError(400, "Ce modèle n'existe pas.")
    return modele


# --- Consultation ------------------------------------------------------------------


@router.get("/projets/{projet_id}/consultation", response=ConsultationSchema)
def lire_consultation(request, projet_id: int):
    return _consultation_out(get_object_or_404(Projet, pk=projet_id))


@router.put("/projets/{projet_id}/consultation", response=ConsultationSchema)
def enregistrer_consultation(request, projet_id: int, donnees: ConsultationSchema):
    projet = get_object_or_404(Projet, pk=projet_id)
    if donnees.criteres:
        somme = sum(c.ponderation for c in donnees.criteres)
        if somme != 100:
            raise HttpError(400, f"La somme des pondérations doit faire 100 % (actuellement {somme} %).")
    consultation = consultation_du_projet(projet)
    valeurs = donnees.model_dump()
    if valeurs["date_limite_offres"] is not None and timezone.is_naive(valeurs["date_limite_offres"]):
        valeurs["date_limite_offres"] = timezone.make_aware(valeurs["date_limite_offres"])
    for champ, valeur in valeurs.items():
        setattr(consultation, champ, valeur)
    consultation.save()
    return _consultation_out(projet)


# --- Modèles -------------------------------------------------------------------------


@router.get("/modeles", response=list[ModeleOut])
def lister_modeles(request, type_piece: TypePiece | None = None):
    return [{**m, "nb_clauses": len(m["clauses"])} for m in modeles_service.lister_modeles(type_piece)]


@router.post("/pieces/{piece_id}/enregistrer-modele", response={201: ModeleOut})
def enregistrer_modele(request, piece_id: int, donnees: NouveauModele):
    modele = pieces.enregistrer_comme_modele(_piece(piece_id), donnees.nom.strip(), request.auth)
    return 201, {
        "id": f"cabinet-{modele.pk}",
        "nom": modele.nom,
        "type_piece": modele.type_piece,
        "marche": modele.marche,
        "origine": "CABINET",
        "nb_clauses": len(modele.clauses),
    }


@router.delete("/modeles/{modele_id}", response={204: None})
def supprimer_modele(request, modele_id: str):
    if not modele_id.startswith("cabinet-") or not modele_id[8:].isdigit():
        raise HttpError(400, "Seuls les modèles du cabinet peuvent être supprimés.")
    get_object_or_404(ModelePiece, pk=int(modele_id[8:])).delete()
    return 204, None


# --- Pièces --------------------------------------------------------------------------


@router.get("/projets/{projet_id}/pieces", response=list[PieceResume])
def lister_pieces(request, projet_id: int):
    projet = get_object_or_404(Projet, pk=projet_id)
    return [_resume(p) for p in projet.pieces.select_related("lot")]


@router.post("/projets/{projet_id}/pieces", response={201: PieceDetail})
def creer_piece(request, projet_id: int, donnees: CreationPiece):
    projet = get_object_or_404(Projet, pk=projet_id)
    lot = get_object_or_404(LotProjet, pk=donnees.lot_id, projet=projet) if donnees.lot_id else None
    document = get_object_or_404(DocumentReference, pk=donnees.document_id) if donnees.document_id else None
    try:
        piece = pieces.creer_piece(projet, donnees.type_piece, lot, modele=_modele(donnees.modele_id), document=document)
    except (pieces.PieceInvalide, IntegrityError) as erreur:
        raise HttpError(409, str(erreur) if isinstance(erreur, pieces.PieceInvalide) else "Cette pièce existe déjà.") from None
    return 201, _detail(piece)


@router.post("/projets/{projet_id}/pieces/actes-engagement", response={201: list[PieceResume]})
def creer_actes_engagement(request, projet_id: int, donnees: CreationActes):
    """Crée l'acte d'engagement de chaque lot qui n'en a pas encore."""
    projet = get_object_or_404(Projet, pk=projet_id)
    modele = _modele(donnees.modele_id)
    existants = set(projet.pieces.filter(type_piece=TypePiece.AE).values_list("lot_id", flat=True))
    crees = [
        pieces.creer_piece(projet, TypePiece.AE, lot, modele=modele)
        for lot in projet.lots.order_by("ordre", "code")
        if lot.pk not in existants
    ]
    return 201, [_resume(p) for p in crees]


@router.get("/pieces/{piece_id}", response=PieceDetail)
def detail_piece(request, piece_id: int):
    return _detail(_piece(piece_id))


@router.patch("/pieces/{piece_id}", response=PieceDetail)
def modifier_piece(request, piece_id: int, donnees: PieceModification):
    piece = _piece(piece_id)
    piece.titre = donnees.titre.strip()
    piece.save(update_fields=["titre", "modifie_le"])
    return _detail(piece)


@router.delete("/pieces/{piece_id}", response={204: None})
def supprimer_piece(request, piece_id: int):
    _piece(piece_id).delete()
    return 204, None


@router.get("/pieces/{piece_id}/champs", response=list[ChampOut])
def champs_piece(request, piece_id: int):
    piece = _piece(piece_id)
    return [
        {"cle": c.cle, "libelle": c.libelle, "apercu": c.apercu, "renseigne": c.renseigne, "bloc": c.bloc}
        for c in champs_du_projet(piece.projet, piece.lot).values()
    ]


# --- Clauses ------------------------------------------------------------------------


@router.post("/pieces/{piece_id}/clauses", response={201: PieceDetail})
def ajouter_clause(request, piece_id: int, donnees: ClauseIn):
    piece = _piece(piece_id)
    clause = Clause(piece=piece, genre=donnees.genre, titre=donnees.titre.strip(), contenu=nettoyer_html(donnees.contenu))
    ordre.inserer(pieces.clauses_ordonnees(piece), [clause], donnees.apres_id)
    _toucher(piece)
    return 201, _detail(piece)


@router.patch("/clauses/{clause_id}", response=PieceDetail)
def modifier_clause(request, clause_id: int, donnees: ClauseModification):
    clause = get_object_or_404(Clause.objects.select_related("piece__projet", "piece__lot"), pk=clause_id)
    champs = donnees.model_dump(exclude_unset=True)
    if champs.get("genre"):
        clause.genre = champs["genre"]
    if champs.get("titre"):
        clause.titre = champs["titre"].strip()
    if "contenu" in champs:
        clause.contenu = nettoyer_html(champs["contenu"] or "")
    clause.save()
    _toucher(clause.piece)
    return _detail(clause.piece)


@router.delete("/clauses/{clause_id}", response=PieceDetail)
def supprimer_clause(request, clause_id: int):
    clause = get_object_or_404(Clause.objects.select_related("piece__projet", "piece__lot"), pk=clause_id)
    piece = clause.piece
    clause.delete()
    _toucher(piece)
    return _detail(piece)


@router.post("/clauses/{clause_id}/deplacer", response=PieceDetail)
def deplacer_clause(request, clause_id: int, donnees: Deplacement):
    clause = get_object_or_404(Clause.objects.select_related("piece__projet", "piece__lot"), pk=clause_id)
    ordre.deplacer(pieces.clauses_ordonnees(clause.piece), clause, donnees.sens)
    return _detail(clause.piece)


@router.post("/pieces/{piece_id}/importer", response=PieceDetail)
def importer_document(request, piece_id: int, donnees: ImportDocument):
    piece = _piece(piece_id)
    document = get_object_or_404(DocumentReference, pk=donnees.document_id)
    if pieces.importer_document(piece, document, donnees.apres_id) == 0:
        raise HttpError(400, "Ce document ne contient aucune clause exploitable.")
    _toucher(piece)
    return _detail(piece)


@router.post("/pieces/{piece_id}/inserer-article", response=PieceDetail)
def inserer_article(request, piece_id: int, donnees: InsertionArticle):
    piece = _piece(piece_id)
    pieces.inserer_article(piece, get_object_or_404(Article, pk=donnees.article_id), donnees.apres_id)
    _toucher(piece)
    return _detail(piece)


# --- Exports -------------------------------------------------------------------------

TYPES_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


@router.get("/pieces/{piece_id}/export/{format_fichier}")
def exporter_piece(request, piece_id: int, format_fichier: Literal["docx", "pdf"]):
    document = pieces.document_piece(_piece(piece_id))
    contenu = exporter_docx(document) if format_fichier == "docx" else exporter_pdf(document)
    reponse = HttpResponse(contenu, content_type=TYPES_MIME[format_fichier])
    reponse["Content-Disposition"] = content_disposition_header(
        format_fichier == "docx", nom_de_fichier(document.nom_fichier, format_fichier)
    )
    return reponse
