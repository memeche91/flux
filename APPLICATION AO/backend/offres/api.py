"""API de l'analyse des offres (étape 3) : offres reçues, comparatif, notation, rapport ACT."""
from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.http import content_disposition_header
from ninja import Field, File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from dce.models import ConsultationEntreprise, StatutConsultation
from entreprises.models import Entreprise
from projets.exports.cctp_docx import exporter_docx
from projets.exports.document import nom_de_fichier
from projets.exports.pdf import exporter_pdf
from projets.models import LotProjet, OptionLot, Projet

from .comparatif import comparatif, comparatif_xlsx
from .models import AnalyseLot, MethodePrix, Offre, StatutLecture
from .notation import analyse_du_lot, classer, estimation
from .rapport import document_rapport
from .tasks import analyser_offre

router = Router(tags=["Analyse des offres"])
EXTENSIONS_OFFRES = {".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".pdf", ".docx", ".doc", ".odt"}
TYPES_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class ModificationOffre(Schema):
    montant_base: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    montants_options: dict[str, Decimal | None] | None = None
    variante: bool | None = None
    libelle_variante: str | None = Field(None, max_length=255)
    recue_le: datetime.date | None = None
    delai_propose: str | None = Field(None, max_length=255)
    commentaire: str | None = None
    ecartee: bool | None = None
    motif_ecart: str | None = Field(None, max_length=500)
    notes: dict[str, dict] | None = None


class ParametresAnalyse(Schema):
    methode_prix: MethodePrix | None = None
    bareme: int | None = Field(None, ge=1, le=100)
    options_retenues: list[int] | None = None
    seuil_anormal: int | None = Field(None, ge=0, le=90)
    attributaire_id: int | None = None
    observations: str | None = None


def _n(valeur) -> float | None:
    return None if valeur is None else float(valeur)


def _offre(o: Offre, ligne=None) -> dict:
    return {
        "id": o.pk, "entreprise_id": o.entreprise_id, "entreprise": o.entreprise.raison_sociale, "nom": o.nom,
        "variante": o.variante, "libelle_variante": o.libelle_variante, "recue_le": o.recue_le, "nom_original": o.nom_original,
        "a_un_fichier": bool(o.fichier), "statut_lecture": o.statut_lecture, "statut_libelle": o.get_statut_lecture_display(),
        "message_lecture": o.message_lecture, "montant_base": _n(o.montant_base), "montant_base_calcule": _n(o.montant_base_calcule),
        "montant_base_declare": _n(o.montant_base_declare), "montants_options": {k: (None if v in (None, "") else float(v)) for k, v in o.montants_options.items()},
        "delai_propose": o.delai_propose, "commentaire": o.commentaire, "ecartee": o.ecartee, "motif_ecart": o.motif_ecart, "notes": o.notes,
        "prix": _n(ligne.prix) if ligne else None, "incomplete": ligne.incomplete if ligne else False,
        "anormalement_basse": ligne.anormalement_basse if ligne else False, "ecart_estimation": _n(ligne.ecart_estimation) if ligne else None,
        "ecart_moyenne": _n(ligne.ecart_moyenne) if ligne else None,
        "notes_calculees": {k: _n(v) for k, v in (ligne.notes if ligne else {}).items()}, "total": _n(ligne.total) if ligne else None,
        "rang": ligne.rang if ligne else None, "notation_complete": ligne.notation_complete if ligne else True,
    }


def _lot(lot: LotProjet) -> dict:
    analyse, criteres, lignes = classer(lot)
    reference = estimation(lot)
    avec_offre = {l.offre.entreprise_id for l in lignes}
    consultees = [
        {"entreprise_id": c.entreprise_id, "entreprise": c.entreprise.raison_sociale, "statut": c.statut}
        for c in ConsultationEntreprise.objects.filter(lot=lot).select_related("entreprise")
        if c.entreprise_id not in avec_offre
    ]
    return {
        "id": lot.pk, "code": lot.code, "intitule": lot.intitule,
        "options": [{"id": o.pk, "nom": o.nom_court, "libelle": o.libelle} for o in lot.options.all()],
        "estimation_base": _n(reference["base"]), "estimation_options": {str(k): _n(v) for k, v in reference["options"].items()},
        "analyse": {
            "methode_prix": analyse.methode_prix, "bareme": analyse.bareme, "seuil_anormal": analyse.seuil_anormal,
            "options_retenues": list(analyse.options_retenues.values_list("pk", flat=True)),
            "attributaire_id": analyse.attributaire_id, "observations": analyse.observations, "validee_le": analyse.validee_le,
        },
        "criteres": [{"libelle": c["libelle"], "ponderation": _n(c["ponderation"]), "prix": c["prix"]} for c in criteres],
        "offres": [_offre(l.offre, l) for l in lignes],
        "consultees_sans_offre": consultees,
    }


def _lot_projet(lot_id: int) -> LotProjet:
    return get_object_or_404(LotProjet.objects.select_related("projet"), pk=lot_id)


@router.get("/projets/{projet_id}/offres")
def etat(request, projet_id: int):
    projet = get_object_or_404(Projet, pk=projet_id)
    return {
        "type_marche": projet.type_marche,
        "taux_tva": _n(projet.taux_tva),
        "lots": [_lot(lot) for lot in projet.lots.order_by("ordre", "code").prefetch_related("options")],
    }


@router.get("/lots-projet/{lot_id}/offres")
def etat_lot(request, lot_id: int):
    return _lot(_lot_projet(lot_id))


@router.post("/lots-projet/{lot_id}/offres", response={201: dict})
def ajouter(
    request,
    lot_id: int,
    entreprise_id: Form[int],
    fichier: File[UploadedFile | None] = None,
    variante: Form[bool] = False,
    libelle_variante: Form[str] = "",
    montant_base: Form[str] = "",
):
    lot = _lot_projet(lot_id)
    entreprise = get_object_or_404(Entreprise, pk=entreprise_id)
    if not variante and Offre.objects.filter(lot=lot, entreprise=entreprise, variante=False).exists():
        raise HttpError(409, f"Une offre de {entreprise.raison_sociale} est déjà enregistrée pour ce lot : remplacez son fichier ou supprimez-la.")
    offre = Offre(projet=lot.projet, lot=lot, entreprise=entreprise, variante=variante, libelle_variante=libelle_variante.strip()[:255])
    if fichier is not None:
        extension = Path(fichier.name or "").suffix.lower()
        if extension not in EXTENSIONS_OFFRES:
            raise HttpError(400, f"Format « {extension or 'inconnu'} » non lu. Formats possibles : {', '.join(sorted(EXTENSIONS_OFFRES))}.")
        if fichier.size > settings.TAILLE_MAX_FICHIER_MO * 1024 * 1024:
            raise HttpError(400, f"Fichier trop volumineux (maximum {settings.TAILLE_MAX_FICHIER_MO} Mo).")
        offre.nom_original = (fichier.name or "offre")[:255]
        offre.fichier.save(fichier.name or f"offre{extension}", fichier, save=False)
        offre.statut_lecture = StatutLecture.EN_COURS
    elif montant_base.strip():
        offre.montant_base = _decimal(montant_base)
    offre.save()
    # L'entreprise passe à « A remis une offre » dans la consultation (historique de l'annuaire).
    consultation, _ = ConsultationEntreprise.objects.get_or_create(projet=lot.projet, lot=lot, entreprise=entreprise)
    if consultation.statut in (StatutConsultation.A_CONSULTER, StatutConsultation.CONSULTEE, StatutConsultation.EXCUSEE):
        consultation.statut = StatutConsultation.REPONDU
        consultation.consultee_le = consultation.consultee_le or timezone.localdate()
        consultation.save(update_fields=["statut", "consultee_le"])
    if offre.fichier:
        transaction.on_commit(lambda: analyser_offre.delay(offre.pk))
    return 201, _offre(Offre.objects.select_related("entreprise").get(pk=offre.pk))


def _decimal(texte: str) -> Decimal:
    try:
        valeur = Decimal(texte.replace(" ", "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise HttpError(400, "Montant invalide.") from None
    if valeur < 0:
        raise HttpError(400, "Montant invalide.")
    return valeur.quantize(Decimal("0.01"))


@router.patch("/offres/{offre_id}")
def modifier(request, offre_id: int, donnees: ModificationOffre):
    offre = get_object_or_404(Offre.objects.select_related("entreprise", "lot"), pk=offre_id)
    champs = donnees.model_dump(exclude_unset=True)
    if "montant_base" in champs:
        offre.montant_base = champs["montant_base"]
        if offre.statut_lecture in (StatutLecture.NON_LUE, StatutLecture.MANUELLE) or offre.montant_base != offre.montant_base_declare:
            offre.statut_lecture = StatutLecture.MANUELLE if not offre.fichier else offre.statut_lecture
    if champs.get("montants_options") is not None:
        valides = {str(o) for o in offre.lot.options.values_list("pk", flat=True)}
        if set(champs["montants_options"]) - valides:
            raise HttpError(400, "PSE inconnue pour ce lot.")
        offre.montants_options = {**offre.montants_options, **{k: (None if v is None else str(v)) for k, v in champs["montants_options"].items()}}
    for champ in ("variante", "recue_le", "ecartee"):
        if champs.get(champ) is not None:
            setattr(offre, champ, champs[champ])
    for champ in ("libelle_variante", "delai_propose", "commentaire", "motif_ecart"):
        if champ in champs and champs[champ] is not None:
            setattr(offre, champ, champs[champ].strip())
    if champs.get("notes") is not None:
        notes = dict(offre.notes)
        for critere, saisie in champs["notes"].items():
            note = saisie.get("note")
            if note not in (None, ""):
                try:
                    note = float(str(note).replace(",", "."))
                except ValueError:
                    raise HttpError(400, f"Note invalide pour « {critere} ».") from None
                bareme = analyse_du_lot(offre.lot).bareme
                if not 0 <= note <= bareme:
                    raise HttpError(400, f"La note « {critere} » doit être comprise entre 0 et {bareme}.")
            notes[critere[:255]] = {"note": None if note in (None, "") else note, "commentaire": str(saisie.get("commentaire") or "")[:4000]}
        offre.notes = notes
    offre.save()
    return _lot(offre.lot)


@router.delete("/offres/{offre_id}", response={204: None})
def supprimer(request, offre_id: int):
    offre = get_object_or_404(Offre, pk=offre_id)
    lot, entreprise = offre.lot, offre.entreprise
    with transaction.atomic():
        offre.delete()
        if not Offre.objects.filter(lot=lot, entreprise=entreprise).exists():
            ConsultationEntreprise.objects.filter(
                lot=lot, entreprise=entreprise,
                statut__in=[StatutConsultation.REPONDU, StatutConsultation.RETENUE, StatutConsultation.NON_RETENUE],
            ).update(statut=StatutConsultation.CONSULTEE)
        # Le classement a changé : la proposition d'attribution est à valider de nouveau.
        AnalyseLot.objects.filter(lot=lot).update(validee_le=None)
    return 204, None


@router.post("/offres/{offre_id}/relire", response={202: dict})
def relire(request, offre_id: int):
    offre = get_object_or_404(Offre.objects.select_related("entreprise"), pk=offre_id)
    if not offre.fichier:
        raise HttpError(400, "Aucun document à relire pour cette offre.")
    offre.statut_lecture = StatutLecture.EN_COURS
    offre.save(update_fields=["statut_lecture"])
    transaction.on_commit(lambda: analyser_offre.delay(offre.pk))
    return 202, _offre(offre)


@router.get("/offres/{offre_id}/fichier")
def fichier(request, offre_id: int):
    from django.http import FileResponse

    offre = get_object_or_404(Offre, pk=offre_id)
    if not offre.fichier:
        raise HttpError(404, "Aucun document.")
    return FileResponse(offre.fichier.open("rb"), as_attachment=False, filename=offre.nom_original or "offre")


@router.get("/lots-projet/{lot_id}/comparatif")
def tableau_comparatif(request, lot_id: int):
    return comparatif(_lot_projet(lot_id))


@router.patch("/lots-projet/{lot_id}/analyse")
def parametres(request, lot_id: int, donnees: ParametresAnalyse):
    lot = _lot_projet(lot_id)
    analyse = analyse_du_lot(lot)
    champs = donnees.model_dump(exclude_unset=True)
    for champ in ("methode_prix", "bareme", "seuil_anormal", "observations"):
        if champs.get(champ) is not None:
            setattr(analyse, champ, champs[champ])
    if "attributaire_id" in champs:
        analyse.attributaire = get_object_or_404(Offre, pk=champs["attributaire_id"], lot=lot) if champs["attributaire_id"] else None
    analyse.save()
    if champs.get("options_retenues") is not None:
        options = list(OptionLot.objects.filter(lot=lot, pk__in=champs["options_retenues"]))
        if len(options) != len(set(champs["options_retenues"])):
            raise HttpError(400, "PSE inconnue pour ce lot.")
        analyse.options_retenues.set(options)
    return _lot(lot)


@router.post("/lots-projet/{lot_id}/analyse/valider")
def valider(request, lot_id: int):
    """Proposition validée : l'entreprise proposée passe à « Retenue », les autres à « Non retenue »."""
    lot = _lot_projet(lot_id)
    analyse, _, lignes = classer(lot)
    proposee = analyse.attributaire or next((l.offre for l in lignes if l.rang == 1), None)
    if proposee is None:
        raise HttpError(400, "Aucune offre classée pour ce lot.")
    with transaction.atomic():
        analyse.attributaire, analyse.validee_le = proposee, timezone.now()
        analyse.save(update_fields=["attributaire", "validee_le"])
        for offre in Offre.objects.filter(lot=lot):
            ConsultationEntreprise.objects.filter(lot=lot, entreprise=offre.entreprise).update(
                statut=StatutConsultation.RETENUE if offre.entreprise_id == proposee.entreprise_id else StatutConsultation.NON_RETENUE
            )
    return _lot(lot)


@router.get("/projets/{projet_id}/rapport-act/{format_fichier}")
def rapport(request, projet_id: int, format_fichier: Literal["docx", "pdf"], lot_id: int | None = None):
    projet = get_object_or_404(Projet, pk=projet_id)
    lots = [get_object_or_404(LotProjet, pk=lot_id, projet=projet)] if lot_id else None
    document = document_rapport(projet, lots)
    contenu = exporter_docx(document) if format_fichier == "docx" else exporter_pdf(document)
    reponse = HttpResponse(contenu, content_type=TYPES_MIME[format_fichier])
    reponse["Content-Disposition"] = content_disposition_header(format_fichier == "docx", nom_de_fichier(document.nom_fichier, format_fichier))
    return reponse


@router.get("/projets/{projet_id}/comparatif-offres.xlsx")
def comparatif_excel(request, projet_id: int, lot_id: int | None = None):
    projet = get_object_or_404(Projet, pk=projet_id)
    lots = [get_object_or_404(LotProjet, pk=lot_id, projet=projet)] if lot_id else list(projet.lots.order_by("ordre", "code"))
    reponse = HttpResponse(comparatif_xlsx(lots), content_type=TYPES_MIME["xlsx"])
    reponse["Content-Disposition"] = content_disposition_header(True, nom_de_fichier(f"Comparatif des offres - {projet.nom}", "xlsx"))
    return reponse
