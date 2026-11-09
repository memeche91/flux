"""Pièces administratives : CCAP et RC (un par projet), actes d'engagement (un par lot)."""
from __future__ import annotations

import re

from django.db import transaction

from articles.models import Article
from articles.normalisation import normaliser
from bibliotheque.models import DocumentReference

from . import ordre
from .champs import champs_du_projet, remplacer_champs, remplacer_dans_titre
from .exports.document import ChapitreDoc, DocumentExport, ElementDoc
from .html import nettoyer_html, texte_propre, texte_vers_html
from .models import Clause, GenreClause, LotProjet, ModelePiece, PieceEcrite, Projet, TypePiece

TITRES = {
    TypePiece.CCAP: "Cahier des Clauses Administratives Particulières",
    TypePiece.RC: "Règlement de la Consultation",
    TypePiece.AE: "Acte d'Engagement",
}


class PieceInvalide(Exception):
    pass


def clauses_ordonnees(piece: PieceEcrite) -> list[Clause]:
    return list(piece.clauses.order_by("ordre", "id"))


def numeroter(clauses: list[Clause]) -> dict[int, tuple[str, str]]:
    """Numéro et intitulé de chaque clause : « Article 3 – Prix », « 3.1 Forme des prix »."""
    resultat: dict[int, tuple[str, str]] = {}
    article = sous_article = 0
    for clause in clauses:
        if clause.genre == GenreClause.CHAPITRE:
            article += 1
            sous_article = 0
            resultat[clause.pk] = (f"Article {article}", f"Article {article} – {clause.titre}")
        else:
            sous_article += 1
            numero = f"{article}.{sous_article}"
            resultat[clause.pk] = (numero, f"{numero} {clause.titre}")
    return resultat


def _clauses_depuis_modele(piece: PieceEcrite, modele: dict) -> list[Clause]:
    return [
        Clause(
            piece=piece,
            genre=GenreClause.CHAPITRE if c.get("genre") == "CHAPITRE" else GenreClause.ARTICLE,
            titre=texte_propre(c.get("titre") or "")[:500] or "Sans titre",
            contenu=nettoyer_html(c.get("contenu") or ""),
        )
        for c in modele["clauses"]
    ]


_NUMERO_ARTICLE = re.compile(r"^(?:(?:article|chapitre)\s+)?\d{1,3}(?:\.\d{1,3})*\s*[-–:.]?\s*", re.IGNORECASE)
_RUBRIQUE_LOT = re.compile(r"^lot\s", re.IGNORECASE)


def _sans_numero(intitule: str) -> str:
    """« ARTICLE 2 – PRIX » → « PRIX » : l'application renumérote elle-même les clauses."""
    return _NUMERO_ARTICLE.sub("", intitule).strip() or intitule.strip()


def _titre_clause(article: Article) -> str:
    return texte_propre(_sans_numero(article.titre))[:500] or "Sans titre"


def _clauses_depuis_document(piece: PieceEcrite, document: DocumentReference) -> list[Clause]:
    """Reprend les clauses d'un ancien document.

    Les titres de premier niveau deviennent des articles, tous les niveaux inférieurs
    des sous-articles (la pièce n'a que deux niveaux). Un article sans texte propre
    (seulement des sous-articles) est reconstitué à partir de la rubrique de ses sous-articles.
    """
    clauses: list[Clause] = []
    chapitre_courant = None
    for article in Article.objects.filter(document=document).order_by("ordre"):
        titre = _titre_clause(article)
        if article.niveau <= 1:
            chapitre_courant = normaliser(titre)
            genre = GenreClause.CHAPITRE
        else:
            rubriques = [
                texte_propre(_sans_numero(r))
                for r in (article.chemin.split(" › ") if article.chemin else [])
                if r.strip() and not _RUBRIQUE_LOT.match(r.strip())
            ]
            rubriques = [r for r in rubriques if r]
            if rubriques and chapitre_courant not in {normaliser(r) for r in rubriques}:
                clauses.append(Clause(piece=piece, genre=GenreClause.CHAPITRE, titre=rubriques[0][:500]))
                chapitre_courant = normaliser(rubriques[0])
            genre = GenreClause.ARTICLE
        clauses.append(
            Clause(
                piece=piece,
                genre=genre,
                titre=titre,
                contenu=texte_vers_html(article.contenu),
                article_source=article,
            )
        )
    return clauses


@transaction.atomic
def creer_piece(
    projet: Projet,
    type_piece: str,
    lot: LotProjet | None = None,
    *,
    modele: dict | None = None,
    document: DocumentReference | None = None,
) -> PieceEcrite:
    if type_piece == TypePiece.AE and lot is None:
        raise PieceInvalide("Un acte d'engagement se rédige pour un lot : choisissez le lot.")
    if type_piece != TypePiece.AE:
        lot = None
    if PieceEcrite.objects.filter(projet=projet, type_piece=type_piece, lot=lot).exists():
        cible = f"le lot {lot.code}" if lot else "ce projet"
        raise PieceInvalide(f"Cette pièce existe déjà pour {cible}.")

    origine = "Page blanche"
    if modele is not None:
        origine = f"Modèle : {modele['nom']}"
    elif document is not None:
        origine = f"Document : {document.nom_original}"
    piece = PieceEcrite.objects.create(projet=projet, type_piece=type_piece, lot=lot, titre=TITRES[type_piece], origine=origine[:255])

    if modele is not None:
        clauses = _clauses_depuis_modele(piece, modele)
    elif document is not None:
        clauses = _clauses_depuis_document(piece, document)
    else:
        clauses = [Clause(piece=piece, genre=GenreClause.CHAPITRE, titre="Objet")]
    ordre.inserer([], clauses)
    return piece


def importer_document(piece: PieceEcrite, document: DocumentReference, apres_id: int | None = None) -> int:
    clauses = _clauses_depuis_document(piece, document)
    ordre.inserer(clauses_ordonnees(piece), clauses, apres_id)
    return len(clauses)


def inserer_article(piece: PieceEcrite, article: Article, apres_id: int | None = None) -> Clause:
    clause = Clause(
        piece=piece,
        genre=GenreClause.CHAPITRE if article.niveau <= 1 else GenreClause.ARTICLE,
        titre=_titre_clause(article),
        contenu=texte_vers_html(article.contenu),
        article_source=article,
    )
    ordre.inserer(clauses_ordonnees(piece), [clause], apres_id)
    return clause


def enregistrer_comme_modele(piece: PieceEcrite, nom: str, utilisateur) -> ModelePiece:
    return ModelePiece.objects.create(
        nom=nom,
        type_piece=piece.type_piece,
        marche=piece.projet.type_marche,
        clauses=[{"genre": c.genre, "titre": c.titre, "contenu": c.contenu} for c in clauses_ordonnees(piece)],
        cree_par=utilisateur,
    )


def document_piece(piece: PieceEcrite) -> DocumentExport:
    """Pièce prête à exporter : champs remplacés par les données du projet."""
    projet = piece.projet
    champs = champs_du_projet(projet, piece.lot)
    clauses = clauses_ordonnees(piece)
    intitules = numeroter(clauses)
    chapitres: list[ChapitreDoc] = []
    for clause in clauses:
        intitule = remplacer_dans_titre(intitules[clause.pk][1], champs)
        contenu = remplacer_champs(clause.contenu, champs)
        if clause.genre == GenreClause.CHAPITRE:
            chapitres.append(ChapitreDoc(f"clause-{clause.pk}", intitule, contenu))
        else:
            if not chapitres:
                chapitres.append(ChapitreDoc("preambule", ""))
            chapitres[-1].elements.append(ElementDoc(f"clause-{clause.pk}", intitule, contenu))

    lot = piece.lot
    if lot is not None:
        sous_titre = f"Lot {lot.code} – {lot.intitule}"
        nom = f"{piece.type_piece} Lot {lot.code} - {lot.intitule}"
        pied = f"{projet.nom} – {piece.type_piece} lot {lot.code} – indice {projet.indice}"
    else:
        sous_titre = f"{projet.get_type_marche_display()} de travaux"
        nom = f"{piece.type_piece} - {projet.nom}"
        pied = f"{projet.nom} – {piece.type_piece} – indice {projet.indice}"
    return DocumentExport(
        projet=projet,
        titre_piece=piece.titre,
        sigle=piece.type_piece,
        sous_titre=sous_titre,
        pied=pied,
        nom_fichier=nom,
        chapitres=chapitres,
    )
