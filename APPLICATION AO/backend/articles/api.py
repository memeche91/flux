from collections import Counter, defaultdict
from statistics import median

from ninja import Query, Router, Schema

from bibliotheque.models import TypeDocument
from referentiel.api import LotOut

from .models import Article, Categorie, LignePrix
from .normalisation import normaliser

router = Router(tags=["Articles et prix de référence"])

PAR_PAGE = 50
PAR_PAGE_PRIX = 100
VALEURS_MAX_STATISTIQUES = 20_000


class DocumentSourceOut(Schema):
    id: int
    nom_original: str
    type_document: str
    operation: str
    annee: int | None


class ArticleOut(Schema):
    id: int
    numero: str
    titre: str
    chemin: str
    niveau: int
    contenu: str
    categorie: str
    categorie_libelle: str
    references_normatives: list[str]
    lot: LotOut | None
    document: DocumentSourceOut

    @staticmethod
    def resolve_categorie_libelle(obj):
        return obj.get_categorie_display()

    @staticmethod
    def resolve_references_normatives(obj):
        return obj.liste_references


class PageArticles(Schema):
    total: int
    resultats: list[ArticleOut]


class ReferenceOut(Schema):
    reference: str
    nombre: int


class LignePrixOut(Schema):
    id: int
    numero: str
    chapitre: str
    designation: str
    unite: str
    unite_normalisee: str
    quantite: float | None
    prix_unitaire: float | None
    montant: float | None
    lot: LotOut | None
    document: DocumentSourceOut


class StatistiqueUnite(Schema):
    unite: str
    nombre: int
    minimum: float
    mediane: float
    maximum: float


class PagePrix(Schema):
    total: int
    unites: list[str]
    statistiques: list[StatistiqueUnite]
    resultats: list[LignePrixOut]


def _filtrer_mots(requete, champ: str, recherche: str):
    for mot in normaliser(recherche).split():
        requete = requete.filter(**{f"{champ}__contains": mot})
    return requete


def _articles_filtres(type_document, lot_id, categorie, recherche, reference, document_id):
    articles = Article.objects.select_related("lot", "document")
    if type_document:
        articles = articles.filter(document__type_document=type_document)
    if lot_id:
        articles = articles.filter(lot_id=lot_id)
    if categorie:
        articles = articles.filter(categorie=categorie)
    if document_id:
        articles = articles.filter(document_id=document_id)
    if reference:
        articles = articles.filter(references_normatives__contains=f"|{reference}|")
    return _filtrer_mots(articles, "texte_recherche", recherche)


@router.get("/articles", response=PageArticles)
def lister_articles(
    request,
    type_document: TypeDocument | None = None,
    lot_id: int | None = None,
    categorie: Categorie | None = None,
    recherche: str = "",
    reference: str = "",
    document_id: int | None = None,
    page: int = Query(1, ge=1),
):
    articles = _articles_filtres(type_document, lot_id, categorie, recherche, reference, document_id)
    debut = (page - 1) * PAR_PAGE
    return {
        "total": articles.count(),
        "resultats": list(articles.order_by("-document__ajoute_le", "document_id", "ordre")[debut : debut + PAR_PAGE]),
    }


@router.get("/articles/references", response=list[ReferenceOut])
def references_citees(request, type_document: TypeDocument | None = None, lot_id: int | None = None):
    """Normes et DTU cités dans vos documents, du plus fréquent au moins fréquent."""
    articles = _articles_filtres(type_document, lot_id, None, "", "", None).exclude(references_normatives="")
    compteur: Counter[str] = Counter()
    for chaine in articles.values_list("references_normatives", flat=True).iterator():
        compteur.update(r for r in chaine.strip("|").split("|") if r)
    tries = sorted(compteur.items(), key=lambda element: (-element[1], element[0]))
    return [{"reference": reference, "nombre": nombre} for reference, nombre in tries[:80]]


@router.get("/prix", response=PagePrix)
def lister_prix(
    request,
    recherche: str = "",
    lot_id: int | None = None,
    unite: str = "",
    document_id: int | None = None,
    chiffrees: bool = True,
    page: int = Query(1, ge=1),
):
    lignes = LignePrix.objects.select_related("lot", "document")
    if lot_id:
        lignes = lignes.filter(lot_id=lot_id)
    if document_id:
        lignes = lignes.filter(document_id=document_id)
    if chiffrees:
        lignes = lignes.filter(prix_unitaire__gt=0)
    lignes = _filtrer_mots(lignes, "designation_normalisee", recherche)

    unites = sorted(u for u in lignes.order_by().values_list("unite_normalisee", flat=True).distinct() if u)
    if unite:
        lignes = lignes.filter(unite_normalisee=unite)

    valeurs: dict[str, list] = defaultdict(list)
    chiffrage = lignes.filter(prix_unitaire__gt=0).order_by().values_list("unite_normalisee", "prix_unitaire")
    for code_unite, prix in chiffrage[:VALEURS_MAX_STATISTIQUES]:
        valeurs[code_unite or "—"].append(prix)
    statistiques = [
        {
            "unite": code_unite,
            "nombre": len(prix),
            "minimum": min(prix),
            "mediane": median(prix),
            "maximum": max(prix),
        }
        for code_unite, prix in sorted(valeurs.items(), key=lambda element: -len(element[1]))
    ]

    debut = (page - 1) * PAR_PAGE_PRIX
    return {
        "total": lignes.count(),
        "unites": unites,
        "statistiques": statistiques,
        "resultats": list(lignes.order_by("-document__ajoute_le", "document_id", "ordre")[debut : debut + PAR_PAGE_PRIX]),
    }
