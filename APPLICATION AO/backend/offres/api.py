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
from projets.champs import consultation_du_projet
from projets.exports.cctp_docx import exporter_docx
from projets.exports.document import nom_de_fichier
from projets.exports.pdf import exporter_pdf
from projets.models import LotProjet, OptionLot, Projet

from .comparatif import comparatif, comparatif_xlsx
from .models import AnalyseLot, JustificationPrix, MethodePrix, Offre, StatutLecture
from .notation import analyse_du_lot, classer, estimation, invalider_validation as _invalider, proposition
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
    montants_options: dict[str, Decimal | None] | None = None  # une variante peut être une moins-value
    variante: bool | None = None
    libelle_variante: str | None = Field(None, max_length=255)
    recue_le: datetime.date | None = None
    delai_propose: str | None = Field(None, max_length=255)
    commentaire: str | None = None
    ecartee: bool | None = None
    motif_ecart: str | None = Field(None, max_length=500)
    notes: dict[str, dict] | None = None
    justification_prix: JustificationPrix | None = None
    motif_justification: str | None = Field(None, max_length=4000)


class ParametresAnalyse(Schema):
    methode_prix: MethodePrix | None = None
    bareme: int | None = Field(None, ge=1, le=100)
    options_retenues: list[int] | None = None
    seuil_anormal: int | None = Field(None, ge=0, le=90)
    attributaire_id: int | None = None
    observations: str | None = None


def _n(valeur) -> float | None:
    return None if valeur is None else float(valeur)


def _date_limite(projet: Projet) -> datetime.date | None:
    limite = consultation_du_projet(projet).date_limite_offres
    return timezone.localtime(limite).date() if limite else None


def _offre(o: Offre, ligne=None, limite: datetime.date | None = None) -> dict:
    return {
        "id": o.pk, "entreprise_id": o.entreprise_id, "entreprise": o.entreprise.raison_sociale, "nom": o.nom,
        "variante": o.variante, "libelle_variante": o.libelle_variante, "recue_le": o.recue_le, "nom_original": o.nom_original,
        "hors_delai": bool(limite and o.recue_le and o.recue_le > limite),
        "a_un_fichier": bool(o.fichier), "statut_lecture": o.statut_lecture, "statut_libelle": o.get_statut_lecture_display(),
        "message_lecture": o.message_lecture, "montant_base": _n(o.montant_base), "montant_base_calcule": _n(o.montant_base_calcule),
        "montant_base_declare": _n(o.montant_base_declare), "montants_options": {k: (None if v in (None, "") else float(v)) for k, v in o.montants_options.items()},
        "delai_propose": o.delai_propose, "commentaire": o.commentaire, "ecartee": o.ecartee, "motif_ecart": o.motif_ecart, "notes": o.notes,
        "justification_prix": o.justification_prix, "motif_justification": o.motif_justification,
        "prix": _n(ligne.prix) if ligne else None, "incomplete": ligne.incomplete if ligne else False,
        "anormalement_basse": ligne.anormalement_basse if ligne else False, "ecart_estimation": _n(ligne.ecart_estimation) if ligne else None,
        "ecart_moyenne": _n(ligne.ecart_moyenne) if ligne else None,
        "notes_calculees": {k: _n(v) for k, v in (ligne.notes if ligne else {}).items()}, "total": _n(ligne.total) if ligne else None,
        "rang": ligne.rang if ligne else None, "notation_complete": ligne.notation_complete if ligne else True,
        "motif_non_classee": ligne.motif_non_classee if ligne else "", "variante_sans_base": ligne.variante_sans_base if ligne else False,
    }


def _lot(lot: LotProjet) -> dict:
    analyse, criteres, lignes = classer(lot)
    proposee, choix_perime = proposition(analyse, lignes)
    reference = estimation(lot)
    limite = _date_limite(lot.projet)
    avec_offre = {l.offre.entreprise_id for l in lignes}
    consultees = [
        {"entreprise_id": c.entreprise_id, "entreprise": c.entreprise.raison_sociale, "statut": c.statut}
        for c in ConsultationEntreprise.objects.filter(lot=lot).select_related("entreprise")
        if c.entreprise_id not in avec_offre
    ]
    return {
        "id": lot.pk, "code": lot.code, "intitule": lot.intitule,
        "options": [{"id": o.pk, "nom": o.nom_court, "libelle": o.libelle, "genre": o.genre} for o in lot.options.all()],
        "estimation_base": _n(reference["base"]), "estimation_options": {str(k): _n(v) for k, v in reference["options"].items()},
        "variantes_autorisees": consultation_du_projet(lot.projet).variantes_autorisees,
        "date_limite": limite,
        "analyse": {
            "methode_prix": analyse.methode_prix, "bareme": analyse.bareme, "seuil_anormal": analyse.seuil_anormal,
            "options_retenues": list(analyse.options_retenues.values_list("pk", flat=True)),
            "attributaire_id": analyse.attributaire_id, "observations": analyse.observations, "validee_le": analyse.validee_le,
            "proposee_id": proposee.offre.pk if proposee else None, "choix_perime": choix_perime,
        },
        "criteres": [{"libelle": c["libelle"], "ponderation": _n(c["ponderation"]), "prix": c["prix"]} for c in criteres],
        "offres": [_offre(l.offre, l, limite) for l in lignes],
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
    recue_le: Form[datetime.date | None] = None,
):
    lot = _lot_projet(lot_id)
    entreprise = get_object_or_404(Entreprise, pk=entreprise_id)
    if not variante and Offre.objects.filter(lot=lot, entreprise=entreprise, variante=False).exists():
        raise HttpError(409, f"Une offre de {entreprise.raison_sociale} est déjà enregistrée pour ce lot : remplacez son fichier ou supprimez-la.")
    offre = Offre(projet=lot.projet, lot=lot, entreprise=entreprise, variante=variante, libelle_variante=libelle_variante.strip()[:255])
    if recue_le:
        offre.recue_le = _date_de_reception(recue_le)
    elif (limite := _date_limite(lot.projet)) and timezone.localdate() > limite:
        offre.recue_le = limite  # offre saisie après l'ouverture des plis : reçue au plus tard à la date limite
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
    _invalider(lot)
    if offre.fichier:
        transaction.on_commit(lambda: analyser_offre.delay(offre.pk))
    return 201, _offre(Offre.objects.select_related("entreprise").get(pk=offre.pk))


def _decimal(texte: str) -> Decimal:
    try:
        valeur = Decimal(texte.replace(" ", "").replace("\u00a0", "").replace("\u202f", "").replace("€", "").replace(",", "."))
    except InvalidOperation:
        raise HttpError(400, "Montant invalide.") from None
    if not valeur.is_finite() or valeur < 0 or valeur >= Decimal("1e12"):
        raise HttpError(400, "Montant invalide.")
    return valeur.quantize(Decimal("0.01"))


def _euros(valeur: Decimal | None) -> str:
    return "—" if valeur is None else f"{valeur:,.2f}".replace(",", " ").replace(".", ",") + " €"


MOTIF_REJET = "Offre anormalement basse : justifications de prix insuffisantes"


def _date_de_reception(valeur: datetime.date) -> datetime.date:
    if not datetime.date(2000, 1, 1) <= valeur <= timezone.localdate() + datetime.timedelta(days=366):
        raise HttpError(400, "Date de réception invalide.")
    return valeur


@router.patch("/offres/{offre_id}")
def modifier(request, offre_id: int, donnees: ModificationOffre):
    champs = donnees.model_dump(exclude_unset=True)
    with transaction.atomic():
        # Verrou : une lecture qui se termine pendant l'enregistrement n'est ni écrasée ni perdue.
        offre = get_object_or_404(Offre.objects.select_for_update(of=("self",)).select_related("entreprise", "lot__projet"), pk=offre_id)
        modifies: set[str] = set()
        classement_modifie = False

        def changer(champ: str, valeur) -> None:
            if getattr(offre, champ) != valeur:
                setattr(offre, champ, valeur)
                modifies.add(champ)

        if "montant_base" in champs and champs["montant_base"] != offre.montant_base:
            lu = offre.montant_base_declare if offre.montant_base_declare is not None else offre.montant_base_calcule
            changer("montant_base", champs["montant_base"])
            # Montant saisi ou corrigé par l'économiste : il prime sur la lecture (même en cours).
            changer("statut_lecture", StatutLecture.MANUELLE)
            changer("message_lecture", f"Montant saisi à la main (montant lu dans le document : {_euros(lu)})." if offre.fichier and lu is not None else (
                "Montant saisi à la main." if offre.fichier else ""
            ))
            classement_modifie = True
        if champs.get("montants_options") is not None:
            valides = {str(o) for o in offre.lot.options.values_list("pk", flat=True)}
            if set(champs["montants_options"]) - valides:
                raise HttpError(400, "PSE inconnue pour ce lot.")
            options = {**offre.montants_options, **{k: (None if v is None else str(v)) for k, v in champs["montants_options"].items()}}
            classement_modifie = classement_modifie or options != offre.montants_options
            changer("montants_options", options)
        if champs.get("recue_le") is not None:
            changer("recue_le", _date_de_reception(champs["recue_le"]))
            classement_modifie = classement_modifie or "recue_le" in modifies  # hors délai : non classée
        for champ in ("variante", "ecartee"):
            if champs.get(champ) is not None and getattr(offre, champ) != champs[champ]:
                changer(champ, champs[champ])
                classement_modifie = True
        for champ in ("libelle_variante", "delai_propose", "commentaire", "motif_ecart", "motif_justification"):
            if champ in champs and champs[champ] is not None:
                changer(champ, champs[champ].strip())
        if champs.get("justification_prix") is not None and champs["justification_prix"] != offre.justification_prix:
            changer("justification_prix", champs["justification_prix"])
            classement_modifie = True
            if offre.justification_prix == JustificationPrix.REJETEE:
                # Justifications insuffisantes : l'offre anormalement basse est rejetée (art. R2152-3 du CCP).
                changer("ecartee", True)
                changer("motif_ecart", offre.motif_ecart or MOTIF_REJET)
            elif offre.ecartee and offre.motif_ecart == MOTIF_REJET:
                changer("ecartee", False)  # rejet annulé : l'offre est réintégrée
                changer("motif_ecart", "")
        elif champs.get("ecartee") is False and offre.justification_prix == JustificationPrix.REJETEE:
            # Offre réintégrée à la main : le rejet de ses justifications ne vaut plus.
            changer("justification_prix", JustificationPrix.DEMANDEE)
            if offre.motif_ecart == MOTIF_REJET:
                changer("motif_ecart", "")
        if champs.get("notes") is not None:
            notes = dict(offre.notes)
            bareme = analyse_du_lot(offre.lot).bareme
            for critere, saisie in champs["notes"].items():
                note = saisie.get("note")
                if note not in (None, ""):
                    try:
                        note = float(str(note).replace(",", "."))
                    except ValueError:
                        raise HttpError(400, f"Note invalide pour « {critere} ».") from None
                    if not 0 <= note <= bareme:
                        raise HttpError(400, f"La note « {critere} » doit être comprise entre 0 et {bareme}.")
                notes[critere[:255]] = {"note": None if note in (None, "") else note, "commentaire": str(saisie.get("commentaire") or "")[:4000]}
            # Seule une note qui change modifie le classement (pas une appréciation).
            avant = {k: (v or {}).get("note") for k, v in offre.notes.items()}
            apres = {k: (v or {}).get("note") for k, v in notes.items()}
            classement_modifie = classement_modifie or any(avant.get(k) != apres.get(k) for k in avant.keys() | apres.keys())
            changer("notes", notes)
        if modifies:
            offre.save(update_fields=[*modifies, "modifie_le"])
        if offre.ecartee:
            AnalyseLot.objects.filter(lot=offre.lot, attributaire=offre).update(attributaire=None)
        if classement_modifie:
            _invalider(offre.lot)
    return _lot(offre.lot)


@router.delete("/offres/{offre_id}", response={204: None})
def supprimer(request, offre_id: int):
    offre = get_object_or_404(Offre, pk=offre_id)
    lot, entreprise = offre.lot, offre.entreprise
    with transaction.atomic():
        _invalider(lot)
        offre.delete()
        if not Offre.objects.filter(lot=lot, entreprise=entreprise).exists():
            ConsultationEntreprise.objects.filter(
                lot=lot, entreprise=entreprise,
                statut__in=[StatutConsultation.REPONDU, StatutConsultation.RETENUE, StatutConsultation.NON_RETENUE],
            ).update(statut=StatutConsultation.CONSULTEE)
    return 204, None


@router.post("/offres/{offre_id}/relire", response={202: dict})
def relire(request, offre_id: int):
    offre = get_object_or_404(Offre.objects.select_related("entreprise"), pk=offre_id)
    if not offre.fichier:
        raise HttpError(400, "Aucun document à relire pour cette offre.")
    offre.statut_lecture = StatutLecture.EN_COURS
    offre.save(update_fields=["statut_lecture", "modifie_le"])
    _invalider(offre.lot)
    transaction.on_commit(lambda: analyser_offre.delay(offre.pk))
    return 202, _offre(offre)


@router.get("/offres/{offre_id}/fichier")
def fichier(request, offre_id: int):
    from projets.fichiers import reponse_fichier_sure

    offre = get_object_or_404(Offre, pk=offre_id)
    if not offre.fichier:
        raise HttpError(404, "Aucun document.")
    # Fichier remis par une entreprise : affiché seulement s'il s'agit d'un PDF ou d'une image.
    return reponse_fichier_sure(offre.fichier, offre.nom_original or "offre")


@router.get("/lots-projet/{lot_id}/comparatif")
def tableau_comparatif(request, lot_id: int):
    return comparatif(_lot_projet(lot_id))


@router.patch("/lots-projet/{lot_id}/analyse")
def parametres(request, lot_id: int, donnees: ParametresAnalyse):
    lot = _lot_projet(lot_id)
    analyse = analyse_du_lot(lot)
    champs = donnees.model_dump(exclude_unset=True)
    avant = (analyse.methode_prix, analyse.bareme, analyse.seuil_anormal, analyse.attributaire_id, set(analyse.options_retenues.values_list("pk", flat=True)))
    ancien_bareme = analyse.bareme
    for champ in ("methode_prix", "bareme", "seuil_anormal", "observations"):
        if champs.get(champ) is not None:
            setattr(analyse, champ, champs[champ])
    with transaction.atomic():
        if analyse.bareme != ancien_bareme:
            # Notes déjà saisies converties dans le nouveau barème (8/10 devient 16/20).
            for offre in Offre.objects.filter(lot=lot):
                for saisie in offre.notes.values():
                    if isinstance(saisie, dict) and saisie.get("note") not in (None, ""):
                        saisie["note"] = round(float(saisie["note"]) * analyse.bareme / ancien_bareme, 2)
                offre.save(update_fields=["notes"])
        analyse.save()
        if champs.get("options_retenues") is not None:
            options = list(OptionLot.objects.filter(lot=lot, pk__in=champs["options_retenues"]))
            if len(options) != len(set(champs["options_retenues"])):
                raise HttpError(400, "PSE inconnue pour ce lot.")
            analyse.options_retenues.set(options)
        if "attributaire_id" in champs:
            if champs["attributaire_id"]:
                _, _, lignes = classer(lot)
                choisie = next((l for l in lignes if l.offre.pk == champs["attributaire_id"]), None)
                if choisie is None:
                    raise HttpError(404, "Offre introuvable pour ce lot.")
                if not choisie.rang:
                    raise HttpError(400, f"L'offre de {choisie.offre.nom} n'est pas classée ({choisie.motif_non_classee or 'notation incomplète'}) : elle ne peut pas être proposée.")
                analyse.attributaire = choisie.offre
            else:
                analyse.attributaire = None
            analyse.save(update_fields=["attributaire"])
        apres = (analyse.methode_prix, analyse.bareme, analyse.seuil_anormal, analyse.attributaire_id, set(analyse.options_retenues.values_list("pk", flat=True)))
        if apres != avant:
            _invalider(lot)
    return _lot(lot)


@router.post("/lots-projet/{lot_id}/analyse/valider")
def valider(request, lot_id: int):
    """Proposition validée : l'entreprise proposée passe à « Retenue », les autres à « Non retenue »."""
    lot = _lot_projet(lot_id)
    analyse, _, lignes = classer(lot)
    proposee, choix_perime = proposition(analyse, lignes)
    if choix_perime:
        raise HttpError(400, "L'offre choisie n'est plus classée (écartée, incomplète…) : choisissez l'offre à proposer.")
    if proposee is None:
        raise HttpError(400, "Aucune offre classée pour ce lot.")
    if any(l.offre.statut_lecture == StatutLecture.EN_COURS for l in lignes):
        raise HttpError(400, "Une offre est en cours de lecture : attendez la fin de la lecture pour valider.")
    if proposee.anormalement_basse and proposee.offre.justification_prix != JustificationPrix.ACCEPTEE:
        reference = " (articles R2152-3 à R2152-5 du code de la commande publique)" if lot.projet.type_marche == "PUBLIC" else ""
        raise HttpError(
            400,
            f"L'offre de {proposee.offre.nom} paraît anormalement basse : demandez des précisions à l'entreprise et enregistrez "
            f"votre appréciation de ses justifications{reference} avant de la proposer.",
        )
    with transaction.atomic():
        analyse.validee_le = timezone.now()
        analyse.save(update_fields=["validee_le"])
        for offre in Offre.objects.filter(lot=lot):
            ConsultationEntreprise.objects.filter(lot=lot, entreprise=offre.entreprise).update(
                statut=StatutConsultation.RETENUE if offre.entreprise_id == proposee.offre.entreprise_id else StatutConsultation.NON_RETENUE
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
