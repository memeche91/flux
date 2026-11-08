"""Enregistrement des articles et lignes de prix extraits d'un document."""
from dataclasses import dataclass

from django.db import transaction

from referentiel.models import Lot

from .decoupage import decouper
from .models import Article, LignePrix
from .normalisation import normaliser, normaliser_unite
from .prix import extraire_lignes_prix

TYPES_ADMINISTRATIFS = {"CCAP", "AE", "RC"}
CODE_LOT_MULTI = "TCE"


@dataclass
class Bilan:
    articles: int = 0
    lignes_prix: int = 0
    lignes_chiffrees: int = 0


def indexer_document(document, contenu) -> Bilan:
    """Remplace les articles / lignes de prix du document par ceux du contenu lu."""
    lots = {lot.code: lot for lot in Lot.objects.all()}
    # Pour un document « tous corps d'état », le lot est retrouvé dans les titres.
    lot_du_document = document.lot
    detection_lot = lot_du_document is None or lot_du_document.code == CODE_LOT_MULTI

    def lot_pour(code):
        if detection_lot and code in lots:
            return lots[code]
        return lot_du_document

    bilan = Bilan()
    with transaction.atomic():
        Article.objects.filter(document=document).delete()
        LignePrix.objects.filter(document=document).delete()

        if document.type_document == "DPGF":
            lignes = extraire_lignes_prix(contenu.tableaux)
            LignePrix.objects.bulk_create(
                [
                    LignePrix(
                        document=document,
                        lot=lot_pour(ligne.code_lot),
                        ordre=ligne.ordre,
                        numero=ligne.numero,
                        chapitre=ligne.chapitre,
                        designation=ligne.designation,
                        unite=ligne.unite,
                        unite_normalisee=normaliser_unite(ligne.unite) if ligne.unite else "",
                        quantite=ligne.quantite,
                        prix_unitaire=ligne.prix_unitaire,
                        montant=ligne.montant,
                        designation_normalisee=normaliser(f"{ligne.chapitre} {ligne.designation}"),
                    )
                    for ligne in lignes
                ],
                batch_size=500,
            )
            bilan.lignes_prix = len(lignes)
            bilan.lignes_chiffrees = sum(1 for l in lignes if l.prix_unitaire and l.prix_unitaire > 0)
        else:
            articles = decouper(
                contenu.blocs,
                titre_par_defaut=document.nom_original.rsplit(".", 1)[0],
                administratif=document.type_document in TYPES_ADMINISTRATIFS,
            )
            Article.objects.bulk_create(
                [
                    Article(
                        document=document,
                        lot=lot_pour(article.code_lot),
                        ordre=article.ordre,
                        numero=article.numero,
                        titre=article.titre,
                        chemin=article.chemin,
                        niveau=article.niveau,
                        contenu=article.contenu,
                        categorie=article.categorie,
                        references_normatives=f"|{'|'.join(article.references)}|" if article.references else "",
                        texte_recherche=normaliser(
                            f"{article.numero} {article.titre} {article.chemin} {article.contenu}"
                        ),
                    )
                    for article in articles
                ],
                batch_size=500,
            )
            bilan.articles = len(articles)
    return bilan
