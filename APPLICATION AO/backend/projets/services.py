"""Opérations sur les postes d'un lot : ordre, déplacement, reprise depuis la bibliothèque."""
from __future__ import annotations

from django.db import transaction

from articles.models import Article, Categorie, LignePrix
from articles.normalisation import detecter_lot, separer_numero
from bibliotheque.models import DocumentReference, TypeDocument

from . import ordre
from .html import texte_vers_html
from .models import GenrePoste, LotProjet, Poste

CHAPITRES_PAR_DEFAUT = ("Généralités", "Description des ouvrages")


def postes_ordonnes(lot: LotProjet) -> list[Poste]:
    return list(lot.postes.order_by("ordre", "id"))


def creer_chapitres_par_defaut(lot: LotProjet) -> None:
    Poste.objects.bulk_create(
        [Poste(lot=lot, genre=GenrePoste.CHAPITRE, titre=titre, ordre=(i + 1) * 10) for i, titre in enumerate(CHAPITRES_PAR_DEFAUT)]
    )


def inserer(lot: LotProjet, nouveaux: list[Poste], apres: Poste | None = None) -> None:
    """Insère des postes (non enregistrés) après « apres », ou à la fin du lot."""
    for poste in nouveaux:
        poste.lot = lot
    ordre.inserer(postes_ordonnes(lot), nouveaux, apres.pk if apres is not None else None)


def deplacer(poste: Poste, sens: str) -> None:
    """Monte ou descend un poste ; un chapitre se déplace avec tout son contenu."""
    ordre.deplacer(postes_ordonnes(poste.lot), poste, sens)


def _titre_chapitre(rubrique: str, par_defaut: str) -> str:
    if not rubrique or detecter_lot(rubrique):
        return par_defaut
    _, titre = separer_numero(rubrique)
    return titre or par_defaut


def _retirer_chapitres_vides_si_lot_vide(lot: LotProjet) -> None:
    if not lot.postes.exclude(genre=GenrePoste.CHAPITRE).exists():
        lot.postes.all().delete()


@transaction.atomic
def importer_document(lot: LotProjet, document: DocumentReference) -> int:
    """Reprend un ancien CCTP (articles) ou une ancienne DPGF (ouvrages chiffrés)."""
    nouveaux: list[Poste] = []
    chapitre_courant = None

    def chapitre(titre: str):
        nonlocal chapitre_courant
        if titre != chapitre_courant:
            nouveaux.append(Poste(genre=GenrePoste.CHAPITRE, titre=titre[:500]))
            chapitre_courant = titre

    if document.type_document == TypeDocument.DPGF:
        lignes = LignePrix.objects.filter(document=document).order_by("ordre")
        if lot.lot_id and lignes.filter(lot_id=lot.lot_id).exists():
            lignes = lignes.filter(lot_id=lot.lot_id)
        for ligne in lignes:
            chapitre(_titre_chapitre(ligne.chapitre, "Description des ouvrages"))
            nouveaux.append(
                Poste(
                    genre=GenrePoste.OUVRAGE,
                    titre=ligne.designation[:500],
                    description=texte_vers_html(ligne.designation) if len(ligne.designation) > 500 else "",
                    unite=ligne.unite,
                    quantite=ligne.quantite,
                    prix_unitaire=ligne.prix_unitaire,
                )
            )
    else:
        articles = Article.objects.filter(document=document).order_by("ordre")
        # Dans un document tous corps d'état, on ne reprend que le lot concerné.
        if lot.lot_id and articles.filter(lot_id=lot.lot_id).exists():
            articles = articles.filter(lot_id=lot.lot_id)
        for article in articles:
            generalite = article.categorie in {Categorie.GENERALITES, Categorie.CLAUSE}
            rubrique = article.chemin.split(" › ")[-1] if article.chemin else ""
            chapitre(_titre_chapitre(rubrique, "Généralités" if generalite else "Description des ouvrages"))
            nouveaux.append(
                Poste(
                    genre=GenrePoste.ARTICLE if generalite else GenrePoste.OUVRAGE,
                    titre=article.titre[:500],
                    description=texte_vers_html(article.contenu),
                    article_source=article,
                )
            )

    if not nouveaux:
        return 0
    _retirer_chapitres_vides_si_lot_vide(lot)
    inserer(lot, nouveaux)
    return sum(1 for p in nouveaux if p.genre != GenrePoste.CHAPITRE)


def poste_depuis_article(article: Article, genre: str | None = None) -> Poste:
    if genre is None:
        genre = GenrePoste.ARTICLE if article.categorie in {Categorie.GENERALITES, Categorie.CLAUSE} else GenrePoste.OUVRAGE
    return Poste(
        genre=genre,
        titre=article.titre[:500],
        description=texte_vers_html(article.contenu),
        article_source=article,
    )
