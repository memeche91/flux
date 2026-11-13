from django.db import IntegrityError, transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError

from .codes import CODE_LOT_MULTI, cle_tri, code_normalise, verifier_code, verifier_intitule
from .models import Lot

router = Router(tags=["Référentiel"])

LONGUEUR_INTITULE = Lot._meta.get_field("intitule").max_length


class LotOut(Schema):
    id: int
    code: str
    intitule: str


class LotCatalogue(Schema):
    """Lot de la liste proposée à la création des projets (écran « Lots proposés »)."""

    id: int
    code: str
    intitule: str
    actif: bool
    propose: bool
    code_reserve: bool
    utilisations: int
    projets: int


class LotCatalogueIn(Schema):
    code: str
    intitule: str


class LotCatalogueModification(Schema):
    code: str | None = None
    intitule: str | None = None
    propose: bool | None = None


@router.get("/lots", response=list[LotOut])
def lister_lots(request, projets: bool = False):
    """Lots utilisables (bibliothèque, articles, prix, entreprises) ; projets=true : ceux proposés à la création
    des projets."""
    lots = Lot.objects.filter(actif=True)
    return lots.filter(propose=True) if projets else lots


def _administrateur(request) -> None:
    if not request.auth.est_administrateur:
        raise HttpError(403, "La liste des lots proposés se modifie avec un compte administrateur.")


def _comptes(lot_id: int | None = None) -> dict[str, dict[int, int]]:
    """Rattachements de chaque lot, comptés séparément (une seule requête jointe multiplierait les lignes)."""
    from articles.models import Article
    from bibliotheque.models import DocumentReference
    from entreprises.models import Entreprise
    from projets.models import LotProjet

    def par_lot(requete, champ="lot", compte=Count("pk")):
        if lot_id is not None:
            requete = requete.filter(**{champ: lot_id})
        return dict(requete.filter(**{f"{champ}__isnull": False}).values_list(champ).annotate(n=compte).order_by())

    return {
        "documents": par_lot(DocumentReference.objects.all()),
        "articles": par_lot(Article.objects.all()),
        "entreprises": par_lot(Entreprise.lots.through.objects.all()),
        "projets": par_lot(LotProjet.objects.all(), compte=Count("projet", distinct=True)),
    }


def _sortie(lot: Lot, comptes: dict[str, dict[int, int]]) -> dict:
    return {
        "id": lot.pk, "code": lot.code, "intitule": lot.intitule, "actif": lot.actif, "propose": lot.propose,
        "code_reserve": lot.code == CODE_LOT_MULTI,
        "utilisations": sum(comptes[cle].get(lot.pk, 0) for cle in ("documents", "articles", "entreprises")),
        "projets": comptes["projets"].get(lot.pk, 0),
    }


def reordonner_catalogue() -> None:
    """Liste classée par numéro (TCE, 00, 01, 2, 3a, 10…), comme les lots des projets."""
    lots = sorted(Lot.objects.all(), key=lambda lot: (cle_tri(lot.code), lot.pk))
    a_changer = []
    for rang, lot in enumerate(lots):
        if lot.ordre != rang * 10:
            lot.ordre = rang * 10
            a_changer.append(lot)
    Lot.objects.bulk_update(a_changer, ["ordre"])


def _verifier(code: str | None, intitule: str | None, lot: Lot | None = None) -> tuple[str | None, str | None]:
    """Numéro et intitulé vérifiés (None : inchangé). Un numéro inchangé n'est pas revérifié : un lot numéroté
    autrefois « 3 bis » dans l'administration garde son numéro quand on ne modifie que son intitulé."""
    if code is not None and lot is not None and code.strip() == lot.code:
        code = None
    try:
        code = None if code is None else verifier_code(code)
        intitule = None if intitule is None else verifier_intitule(intitule, LONGUEUR_INTITULE)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from None
    if code is not None:
        cle = code_normalise(code)
        autres = Lot.objects.exclude(pk=lot.pk) if lot is not None else Lot.objects.all()
        doublon = next((l for l in autres if code_normalise(l.code) == cle), None)
        if doublon is not None:
            raise HttpError(409, f"Le numéro {code} est déjà celui du lot {doublon.code} – {doublon.intitule}.")
    return code, intitule


@router.get("/lots/tous", response=list[LotCatalogue])
def catalogue_lots(request):
    comptes = _comptes()
    return [_sortie(lot, comptes) for lot in Lot.objects.order_by("ordre", "code")]


@router.post("/lots", response={201: LotCatalogue})
def ajouter_lot_catalogue(request, donnees: LotCatalogueIn):
    _administrateur(request)
    code, intitule = _verifier(donnees.code, donnees.intitule)
    try:
        with transaction.atomic():
            lot = Lot.objects.create(code=code, intitule=intitule)
            reordonner_catalogue()
    except IntegrityError:
        raise HttpError(409, f"Le numéro {code} existe déjà.") from None
    lot.refresh_from_db()
    return 201, _sortie(lot, _comptes(lot.pk))


@router.patch("/lots/{lot_id}", response=LotCatalogue)
def modifier_lot_catalogue(request, lot_id: int, donnees: LotCatalogueModification):
    """Renommer, renuméroter ou ne plus proposer un lot. Les projets existants gardent leurs propres numéros et
    intitulés ; les documents, articles et entreprises rattachés à ce lot affichent le nouveau nom."""
    _administrateur(request)
    lot = get_object_or_404(Lot, pk=lot_id)
    code, intitule = _verifier(donnees.code, donnees.intitule, lot)
    if code is not None and lot.code == CODE_LOT_MULTI:
        raise HttpError(400, "Le numéro TCE est réservé aux documents « tous corps d'état » : seul son intitulé se modifie.")
    if code is not None:
        lot.code = code
    if intitule is not None:
        lot.intitule = intitule
    if donnees.propose is not None:
        lot.propose = donnees.propose
    try:
        with transaction.atomic():
            lot.save()
            reordonner_catalogue()
            if code is not None:
                # Les passages de l'assistant citent le numéro du lot (« lot 08 ») : index remis à jour.
                from assistant.tasks import planifier_indexation

                planifier_indexation()
    except IntegrityError:
        raise HttpError(409, f"Le numéro {code} existe déjà.") from None
    lot.refresh_from_db()
    return _sortie(lot, _comptes(lot.pk))
