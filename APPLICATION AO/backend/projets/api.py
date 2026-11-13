from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Literal

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.http import content_disposition_header
from ninja import Field, Router, Schema
from ninja.errors import HttpError

from articles.models import Article
from bibliotheque.models import DocumentReference, TypeMarche
from referentiel.codes import code_normalise, verifier_code, verifier_intitule
from referentiel.models import Lot

from . import services
from .exports.cctp_docx import exporter_cctp_docx
from .exports.commun import nom_fichier
from .exports.dpgf_xlsx import exporter_dpgf_xlsx
from .exports.pdf import exporter_cctp_pdf, exporter_dpgf_pdf
from .html import nettoyer_html
from .models import GenreOption, GenrePoste, LotProjet, OptionLot, Police, Poste, Projet
from .structure import structurer

router = Router(tags=["Projets et pièces écrites"])

COULEUR = r"^#[0-9A-Fa-f]{6}$"


# --- Schémas -----------------------------------------------------------------


class ProjetIn(Schema):
    nom: str = Field(..., min_length=1, max_length=255)
    numero: str = ""
    maitre_ouvrage: str = ""
    adresse_maitre_ouvrage: str = ""
    adresse_operation: str = ""
    maitre_oeuvre: str = ""
    type_marche: TypeMarche = TypeMarche.PUBLIC
    procedure: str = ""
    phase: str = "DCE"
    indice: str = "A"
    date_document: datetime.date | None = None
    taux_tva: Decimal = Field(Decimal("20"), ge=0, le=100)
    police: Police = Police.ARIAL
    taille_police: int = Field(10, ge=8, le=14)
    couleur_titres: str = Field("#1F3864", pattern=COULEUR)
    couleur_tableaux: str = Field("#D9E2F3", pattern=COULEUR)


class LotChoisi(Schema):
    """Lot retenu à la création du projet : un lot de la liste proposée (numéro et intitulé vides : ceux de la
    liste), ou un lot hors liste (lot_id absent, numéro et intitulé obligatoires)."""

    lot_id: int | None = None
    code: str = Field("", max_length=50)
    intitule: str = Field("", max_length=500)


class ProjetCreation(ProjetIn):
    lots: list[int] = []
    lots_choisis: list[LotChoisi] = []


class ProjetModification(Schema):
    nom: str | None = Field(None, min_length=1, max_length=255)
    numero: str | None = None
    maitre_ouvrage: str | None = None
    adresse_maitre_ouvrage: str | None = None
    adresse_operation: str | None = None
    maitre_oeuvre: str | None = None
    type_marche: TypeMarche | None = None
    procedure: str | None = None
    phase: str | None = None
    indice: str | None = None
    date_document: datetime.date | None = None
    taux_tva: Decimal | None = Field(None, ge=0, le=100)
    police: Police | None = None
    taille_police: int | None = Field(None, ge=8, le=14)
    couleur_titres: str | None = Field(None, pattern=COULEUR)
    couleur_tableaux: str | None = Field(None, pattern=COULEUR)


class ProjetResume(Schema):
    id: int
    nom: str
    numero: str
    maitre_ouvrage: str
    type_marche: str
    phase: str
    modifie_le: datetime.datetime
    nb_lots: int


class LotResume(Schema):
    id: int
    code: str
    lot_id: int | None = None  # lot de la liste proposée dont il vient
    intitule: str
    nb_articles: int
    nb_ouvrages: int
    total_base: float


class ProjetOut(ProjetIn):
    id: int
    lots: list[LotResume]


class OptionOut(Schema):
    id: int
    genre: str
    numero: int
    libelle: str
    nom_court: str
    total: float = 0


class PosteOut(Schema):
    id: int
    genre: str
    numero: str
    titre: str
    description: str
    unite: str
    quantite: float | None
    prix_unitaire: float | None
    montant: float | None
    option_id: int | None
    article_source_id: int | None


class ProjetCourt(Schema):
    id: int
    nom: str
    taux_tva: float


class LotDetail(Schema):
    id: int
    code: str
    intitule: str
    lot_id: int | None
    projet: ProjetCourt
    options: list[OptionOut]
    postes: list[PosteOut]
    total_base: float


class LotIn(Schema):
    lot_id: int | None = None
    code: str = Field("", max_length=50)
    intitule: str = Field("", max_length=500)


class LotModification(Schema):
    code: str | None = Field(None, max_length=50)
    intitule: str | None = Field(None, max_length=500)


class OptionIn(Schema):
    genre: GenreOption = GenreOption.PSE
    libelle: str = Field(..., min_length=1, max_length=255)


class OptionModification(Schema):
    libelle: str = Field(..., min_length=1, max_length=255)


class PosteIn(Schema):
    genre: GenrePoste = GenrePoste.OUVRAGE
    titre: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    unite: str = Field("", max_length=20)
    quantite: Decimal | None = None
    prix_unitaire: Decimal | None = None
    option_id: int | None = None
    apres_id: int | None = None


class PosteModification(Schema):
    genre: GenrePoste | None = None
    titre: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    unite: str | None = Field(None, max_length=20)
    quantite: Decimal | None = None
    prix_unitaire: Decimal | None = None
    option_id: int | None = None


class Deplacement(Schema):
    sens: Literal["haut", "bas"]


class ImportDocument(Schema):
    document_id: int


class InsertionArticle(Schema):
    article_id: int
    apres_id: int | None = None
    genre: GenrePoste | None = None


class ResultatImport(Schema):
    importes: int
    lot: LotDetail


# --- Outils --------------------------------------------------------------------


def _lots_resumes(projet: Projet) -> list[dict]:
    resumes = []
    # order_by explicite : Django n'applique pas l'ordre par défaut (Meta.ordering) à une requête avec Count.
    lots = projet.lots.annotate(
        nb_articles=Count("postes", filter=Q(postes__genre=GenrePoste.ARTICLE)),
        nb_ouvrages=Count("postes", filter=Q(postes__genre=GenrePoste.OUVRAGE)),
    ).order_by("ordre", "code")
    for lot in lots:
        resumes.append(
            {
                "id": lot.pk,
                "code": lot.code,
                "intitule": lot.intitule,
                "lot_id": lot.lot_id,
                "nb_articles": lot.nb_articles,
                "nb_ouvrages": lot.nb_ouvrages,
                "total_base": float(structurer(lot).total_base),
            }
        )
    return resumes


def _projet_out(projet: Projet) -> dict:
    donnees = {champ: getattr(projet, champ) for champ in ProjetIn.model_fields}
    donnees.update({"id": projet.pk, "lots": _lots_resumes(projet)})
    return donnees


def _detail_lot(lot: LotProjet) -> dict:
    structure = structurer(lot)
    totaux_options = {s.option.pk: float(s.total) for s in structure.sections_dpgf if s.option is not None}
    postes = []
    for poste in lot.postes.order_by("ordre", "id"):
        postes.append(
            {
                "id": poste.pk,
                "genre": poste.genre,
                "numero": structure.numeros[poste.pk],
                "titre": poste.titre,
                "description": poste.description,
                "unite": poste.unite,
                "quantite": poste.quantite,
                "prix_unitaire": poste.prix_unitaire,
                "montant": poste.montant,
                "option_id": poste.option_id,
                "article_source_id": poste.article_source_id,
            }
        )
    return {
        "id": lot.pk,
        "code": lot.code,
        "intitule": lot.intitule,
        "lot_id": lot.lot_id,
        "projet": {"id": lot.projet_id, "nom": lot.projet.nom, "taux_tva": lot.projet.taux_tva},
        "options": [
            {
                "id": o.pk,
                "genre": o.genre,
                "numero": o.numero,
                "libelle": o.libelle,
                "nom_court": o.nom_court,
                "total": totaux_options.get(o.pk, 0),
            }
            for o in lot.options.all()
        ],
        "postes": postes,
        "total_base": float(structure.total_base),
    }


def _lot(lot_id: int) -> LotProjet:
    return get_object_or_404(LotProjet.objects.select_related("projet"), pk=lot_id)


def _verifier_option(lot: LotProjet, option_id: int | None) -> OptionLot | None:
    if option_id is None:
        return None
    option = lot.options.filter(pk=option_id).first()
    if option is None:
        raise HttpError(400, "Cette PSE ou variante n'appartient pas à ce lot.")
    return option


def _toucher(projet_id: int) -> None:
    Projet.objects.filter(pk=projet_id).update(modifie_le=datetime.datetime.now(datetime.timezone.utc))


LONGUEUR_INTITULE_LOT = LotProjet._meta.get_field("intitule").max_length


def _numero_et_intitule(code: str | None, intitule: str | None, actuel: str | None = None) -> tuple[str | None, str | None]:
    """Numéro et intitulé d'un lot du projet, vérifiés (None : inchangé). Un numéro inchangé (actuel : celui du lot
    ou de la liste proposée) n'est pas revérifié : un lot numéroté autrefois « 3 bis » reste utilisable."""
    try:
        if code is not None and actuel is not None and code.strip() == actuel:
            code = actuel
        elif code is not None:
            code = verifier_code(code)
        return code, None if intitule is None else verifier_intitule(intitule, LONGUEUR_INTITULE_LOT)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from None


def _numero_libre(projet: Projet, code: str, exclure: int | None = None) -> None:
    """« 3 » et « 03 » désigneraient le même lot dans les pièces : un seul des deux par projet."""
    cle = code_normalise(code)
    doublon = next((l for l in projet.lots.exclude(pk=exclure) if code_normalise(l.code) == cle), None)
    if doublon is not None:
        raise HttpError(409, f"Le numéro {code} est déjà celui du lot {doublon.code} – {doublon.intitule} dans ce projet.")


# --- Projets ---------------------------------------------------------------------


@router.get("/projets", response=list[ProjetResume])
def lister_projets(request):
    # order_by explicite : Django n'applique pas Meta.ordering à une requête avec Count.
    return Projet.objects.annotate(nb_lots=Count("lots")).order_by("-modifie_le", "-id")


@router.post("/projets", response={201: ProjetOut})
def creer_projet(request, donnees: ProjetCreation):
    valeurs = donnees.model_dump(exclude={"lots", "lots_choisis"})
    # Lots retenus : ceux de la liste proposée (numéro et intitulé de la liste, ou ajustés dans le formulaire),
    # et ceux hors liste. « lots » (identifiants seuls) reste accepté.
    demandes = [LotChoisi(lot_id=i) for i in dict.fromkeys(donnees.lots)] + list(donnees.lots_choisis)
    ids = {d.lot_id for d in demandes if d.lot_id is not None}
    references = {lot.pk: lot for lot in Lot.objects.filter(pk__in=ids)}
    if len(references) != len(ids):
        raise HttpError(400, "Un des lots choisis n'existe plus : rechargez la page.")
    retenus, cles = [], {}
    for demande in demandes:
        lot = references.get(demande.lot_id) if demande.lot_id is not None else None
        code, intitule = _numero_et_intitule(
            demande.code if demande.code.strip() or lot is None else lot.code,
            demande.intitule if demande.intitule.strip() or lot is None else lot.intitule,
            actuel=lot.code if lot is not None else None,
        )
        cle = code_normalise(code)
        if cle in cles:
            premier_code, premier_intitule = cles[cle]
            numeros = code if premier_code == code else f"{premier_code} et {code}"
            raise HttpError(409, f"Deux lots ont le même numéro ({numeros}) : {premier_intitule} et {intitule}. Changez l'un des deux.")
        cles[cle] = (code, intitule)
        retenus.append((lot, code, intitule))
    with transaction.atomic():
        projet = Projet.objects.create(**valeurs, cree_par=request.auth)
        for ordre, (lot, code, intitule) in enumerate(retenus):
            lot_projet = LotProjet.objects.create(projet=projet, lot=lot, code=code, intitule=intitule, ordre=ordre)
            services.creer_chapitres_par_defaut(lot_projet)
        services.reordonner_lots(projet)
    return 201, _projet_out(projet)


@router.get("/projets/{projet_id}", response=ProjetOut)
def detail_projet(request, projet_id: int):
    return _projet_out(get_object_or_404(Projet, pk=projet_id))


@router.patch("/projets/{projet_id}", response=ProjetOut)
def modifier_projet(request, projet_id: int, donnees: ProjetModification):
    projet = get_object_or_404(Projet, pk=projet_id)
    champs = donnees.model_dump(exclude_unset=True)
    if "nom" in champs and champs["nom"] is None:
        raise HttpError(400, "Le nom de l'opération est obligatoire.")
    for champ, valeur in champs.items():
        if valeur is None and champ != "date_document":
            continue
        setattr(projet, champ, valeur)
    projet.save()
    return _projet_out(projet)


@router.get("/projets/{projet_id}/bilan")
def bilan_projet(request, projet_id: int):
    """Ce que la suppression du projet ferait perdre (prix reçus, historique de l'annuaire…)."""
    from ged.archivage import bilan_projet as bilan

    return bilan(get_object_or_404(Projet, pk=projet_id))


@router.delete("/projets/{projet_id}", response={204: None})
def supprimer_projet(request, projet_id: int):
    """Suppression totale, réservée à l'administrateur : après un chantier, archivez puis purgez les fichiers."""
    from ninja.errors import HttpError

    if not request.auth.est_administrateur:
        raise HttpError(403, "La suppression d'un projet est réservée à l'administrateur. Pour libérer de la place, archivez le projet puis purgez ses fichiers.")
    get_object_or_404(Projet, pk=projet_id).delete()
    return 204, None


# --- Lots du projet -----------------------------------------------------------------


@router.post("/projets/{projet_id}/lots", response={201: LotResume})
def ajouter_lot(request, projet_id: int, donnees: LotIn):
    projet = get_object_or_404(Projet, pk=projet_id)
    lot_reference = None
    code, intitule = donnees.code.strip(), donnees.intitule.strip()
    if donnees.lot_id is not None:
        lot_reference = get_object_or_404(Lot, pk=donnees.lot_id)
        deja = projet.lots.filter(lot=lot_reference).first()
        if deja is not None:
            raise HttpError(409, f"Ce lot est déjà dans le projet : lot {deja.code} – {deja.intitule}.")
        code = code or lot_reference.code
        intitule = intitule or lot_reference.intitule
    code, intitule = _numero_et_intitule(code, intitule, actuel=lot_reference.code if lot_reference else None)
    _numero_libre(projet, code)
    try:
        with transaction.atomic():
            lot = LotProjet.objects.create(
                projet=projet, lot=lot_reference, code=code, intitule=intitule, ordre=projet.lots.count()
            )
            services.creer_chapitres_par_defaut(lot)
            services.reordonner_lots(projet)
    except IntegrityError:
        raise HttpError(409, f"Le lot {code} existe déjà dans ce projet.") from None
    _toucher(projet.pk)
    return 201, {"id": lot.pk, "code": lot.code, "intitule": lot.intitule, "lot_id": lot.lot_id, "nb_articles": 0, "nb_ouvrages": 0, "total_base": 0}


@router.get("/lots-projet/{lot_id}", response=LotDetail)
def detail_lot(request, lot_id: int):
    return _detail_lot(_lot(lot_id))


@router.patch("/lots-projet/{lot_id}", response=LotDetail)
def modifier_lot(request, lot_id: int, donnees: LotModification):
    """Numéro et intitulé du lot dans ce projet. Les pièces déjà exportées, les DCE déjà assemblés et les
    références déjà attribuées dans la GED gardent l'ancien numéro ; tout ce qui est produit ensuite prend le nouveau."""
    lot = _lot(lot_id)
    code, intitule = _numero_et_intitule(donnees.code, donnees.intitule, actuel=lot.code)
    if code is not None and code != lot.code:
        _numero_libre(lot.projet, code, exclure=lot.pk)
        lot.code = code
    if intitule is not None:
        lot.intitule = intitule
    try:
        with transaction.atomic():
            lot.save(update_fields=["code", "intitule"])
            services.reordonner_lots(lot.projet)
    except IntegrityError:
        raise HttpError(409, "Un autre lot porte déjà ce numéro dans ce projet.") from None
    _toucher(lot.projet_id)
    return _detail_lot(lot)


@router.delete("/lots-projet/{lot_id}", response={204: None})
def supprimer_lot(request, lot_id: int):
    """Un lot vide ou en rédaction se supprime librement ; jamais un lot qui a des documents dans la GED
    (ils ne sont jamais supprimés, seulement annulés), et seul l'administrateur supprime un lot qui a
    des offres ou des consultations (comme pour la suppression d'un projet)."""
    lot = _lot(lot_id)
    if lot.documents_ged.exists():
        raise HttpError(409, "Ce lot a des documents dans la GED du chantier : ils ne sont jamais supprimés (annulez-les si besoin). Le lot est conservé.")
    if not request.auth.est_administrateur and (lot.offres.exists() or lot.consultations_entreprises.exists()):
        raise HttpError(403, "Ce lot a des offres ou des consultations d’entreprises : sa suppression est réservée à l’administrateur.")
    lot.delete()
    return 204, None


# --- PSE et variantes ----------------------------------------------------------------


@router.post("/lots-projet/{lot_id}/options", response={201: LotDetail})
def ajouter_option(request, lot_id: int, donnees: OptionIn):
    lot = _lot(lot_id)
    numero = (lot.options.filter(genre=donnees.genre).order_by("-numero").values_list("numero", flat=True).first() or 0) + 1
    OptionLot.objects.create(lot=lot, genre=donnees.genre, numero=numero, libelle=donnees.libelle.strip())
    return 201, _detail_lot(lot)


@router.patch("/options/{option_id}", response=LotDetail)
def modifier_option(request, option_id: int, donnees: OptionModification):
    option = get_object_or_404(OptionLot.objects.select_related("lot__projet"), pk=option_id)
    option.libelle = donnees.libelle.strip()
    option.save(update_fields=["libelle"])
    return _detail_lot(option.lot)


@router.delete("/options/{option_id}", response=LotDetail)
def supprimer_option(request, option_id: int):
    option = get_object_or_404(OptionLot.objects.select_related("lot__projet"), pk=option_id)
    lot = option.lot
    option.delete()  # les ouvrages concernés reviennent dans la solution de base
    return _detail_lot(lot)


# --- Postes (chapitres, articles, ouvrages) ---------------------------------------------


@router.post("/lots-projet/{lot_id}/postes", response={201: LotDetail})
def ajouter_poste(request, lot_id: int, donnees: PosteIn):
    lot = _lot(lot_id)
    option = _verifier_option(lot, donnees.option_id)
    apres = lot.postes.filter(pk=donnees.apres_id).first() if donnees.apres_id else None
    poste = Poste(
        genre=donnees.genre,
        titre=donnees.titre.strip(),
        description=nettoyer_html(donnees.description),
        unite=donnees.unite.strip(),
        quantite=donnees.quantite,
        prix_unitaire=donnees.prix_unitaire,
        option=option if donnees.genre == GenrePoste.OUVRAGE else None,
    )
    services.inserer(lot, [poste], apres)
    _toucher(lot.projet_id)
    return 201, _detail_lot(lot)


@router.patch("/postes/{poste_id}", response=LotDetail)
def modifier_poste(request, poste_id: int, donnees: PosteModification):
    poste = get_object_or_404(Poste.objects.select_related("lot__projet"), pk=poste_id)
    champs = donnees.model_dump(exclude_unset=True)
    if "option_id" in champs:
        poste.option = _verifier_option(poste.lot, champs.pop("option_id"))
    if "description" in champs:
        champs["description"] = nettoyer_html(champs["description"] or "")
    for champ, valeur in champs.items():
        if champ in {"titre", "genre"} and valeur is None:
            continue
        setattr(poste, champ, valeur.strip() if isinstance(valeur, str) and champ != "description" else valeur)
    if poste.genre != GenrePoste.OUVRAGE:
        poste.option = None
    poste.save()
    _toucher(poste.lot.projet_id)
    return _detail_lot(poste.lot)


@router.delete("/postes/{poste_id}", response=LotDetail)
def supprimer_poste(request, poste_id: int):
    poste = get_object_or_404(Poste.objects.select_related("lot__projet"), pk=poste_id)
    lot = poste.lot
    poste.delete()
    return _detail_lot(lot)


@router.post("/postes/{poste_id}/deplacer", response=LotDetail)
def deplacer_poste(request, poste_id: int, donnees: Deplacement):
    poste = get_object_or_404(Poste.objects.select_related("lot__projet"), pk=poste_id)
    services.deplacer(poste, donnees.sens)
    return _detail_lot(poste.lot)


@router.post("/lots-projet/{lot_id}/importer", response=ResultatImport)
def importer_document(request, lot_id: int, donnees: ImportDocument):
    lot = _lot(lot_id)
    document = get_object_or_404(DocumentReference, pk=donnees.document_id)
    if document.type_document not in {"CCTP", "DPGF"}:
        raise HttpError(400, "Seuls un CCTP ou une DPGF peuvent être repris dans un lot.")
    importes = services.importer_document(lot, document)
    if importes == 0:
        raise HttpError(400, "Ce document ne contient aucun article ou ligne de prix exploitable.")
    _toucher(lot.projet_id)
    return {"importes": importes, "lot": _detail_lot(lot)}


@router.post("/lots-projet/{lot_id}/inserer-article", response=LotDetail)
def inserer_article(request, lot_id: int, donnees: InsertionArticle):
    lot = _lot(lot_id)
    article = get_object_or_404(Article, pk=donnees.article_id)
    apres = lot.postes.filter(pk=donnees.apres_id).first() if donnees.apres_id else None
    services.inserer(lot, [services.poste_depuis_article(article, donnees.genre)], apres)
    _toucher(lot.projet_id)
    return _detail_lot(lot)


# --- Exports ---------------------------------------------------------------------------

TYPES_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@router.get("/lots-projet/{lot_id}/export/{piece}")
def exporter(request, lot_id: int, piece: Literal["cctp-docx", "cctp-pdf", "dpgf-xlsx", "dpgf-pdf"], prix: bool = False):
    structure = structurer(_lot(lot_id))
    suffixe = " (estimation)" if prix and piece.startswith("dpgf") else ""
    if piece == "cctp-docx":
        contenu, extension, sigle = exporter_cctp_docx(structure), "docx", "CCTP"
    elif piece == "cctp-pdf":
        contenu, extension, sigle = exporter_cctp_pdf(structure), "pdf", "CCTP"
    elif piece == "dpgf-xlsx":
        contenu, extension, sigle = exporter_dpgf_xlsx(structure, avec_prix=prix), "xlsx", "DPGF"
    else:
        contenu, extension, sigle = exporter_dpgf_pdf(structure, avec_prix=prix), "pdf", "DPGF"
    reponse = HttpResponse(contenu, content_type=TYPES_MIME[extension])
    nom = nom_fichier(sigle, structure, extension, suffixe)
    disposition = "inline" if extension == "pdf" else "attachment"
    reponse["Content-Disposition"] = content_disposition_header(disposition == "attachment", nom)
    return reponse
