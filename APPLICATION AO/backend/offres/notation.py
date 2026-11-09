"""Analyse d'un lot : prix comparés, détection des offres anormalement basses, notes pondérées, classement.

Les critères et leur pondération sont ceux des paramètres de la consultation (RC). Le critère
« Prix » est noté automatiquement ; les autres le sont par l'économiste (avec commentaire).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from articles.normalisation import normaliser
from projets.champs import consultation_du_projet
from dce.models import ConsultationEntreprise, StatutConsultation
from projets.models import LotProjet
from projets.structure import structurer

from .models import AnalyseLot, MethodePrix, Offre


def criteres(lot: LotProjet) -> list[dict]:
    """Critères de la consultation ; le premier qui parle de prix (ou de coût) est noté automatiquement."""
    liste = [c for c in (consultation_du_projet(lot.projet).criteres or []) if str(c.get("libelle", "")).strip()]
    prix_trouve = False
    resultat = []
    for critere in liste:
        libelle = str(critere["libelle"]).strip()
        est_prix = not prix_trouve and any(m in normaliser(libelle).split() for m in ("prix", "cout", "couts"))
        prix_trouve = prix_trouve or est_prix
        resultat.append({"libelle": libelle, "ponderation": Decimal(str(critere.get("ponderation", 0))), "prix": est_prix})
    return resultat


def analyse_du_lot(lot: LotProjet) -> AnalyseLot:
    analyse, _ = AnalyseLot.objects.get_or_create(lot=lot)
    return analyse


def estimation(lot: LotProjet) -> dict:
    structure = structurer(lot)
    base = structure.sections_dpgf[0].total if structure.sections_dpgf else Decimal("0")
    options = {s.option.pk: s.total for s in structure.sections_dpgf[1:] if s.option is not None}
    return {"base": base, "options": options}


@dataclass
class LigneClassement:
    offre: Offre
    prix: Decimal | None
    incomplete: bool
    anormalement_basse: bool = False
    ecart_estimation: Decimal | None = None
    ecart_moyenne: Decimal | None = None
    notes: dict[str, Decimal | None] = field(default_factory=dict)
    total: Decimal | None = None
    rang: int | None = None
    notation_complete: bool = True
    motif_non_classee: str = ""
    variante_sans_base: bool = False


def _arrondi(valeur: Decimal, decimales: str = "0.01") -> Decimal:
    return valeur.quantize(Decimal(decimales), rounding=ROUND_HALF_UP)


def prix_compare(offre: Offre, options_retenues: list[int]) -> tuple[Decimal | None, bool]:
    """Montant de base + PSE retenues ; `incomplete` si une PSE retenue n'est pas chiffrée."""
    if offre.montant_base is None:
        return None, True
    total = offre.montant_base
    incomplete = False
    for option_id in options_retenues:
        montant = offre.montants_options.get(str(option_id))
        if montant in (None, ""):
            incomplete = True
            continue
        total += Decimal(str(montant))
    return total, incomplete


def classer(lot: LotProjet) -> tuple[AnalyseLot, list[dict], list[LigneClassement]]:
    analyse = analyse_du_lot(lot)
    liste_criteres = criteres(lot)
    retenues = list(analyse.options_retenues.values_list("pk", flat=True))
    reference = estimation(lot)
    montant_estimation = reference["base"] + sum((reference["options"].get(o, Decimal("0")) for o in retenues), Decimal("0"))
    bareme = Decimal(analyse.bareme or 10)

    consultation = consultation_du_projet(lot.projet)
    variantes_autorisees = consultation.variantes_autorisees
    limite = timezone.localtime(consultation.date_limite_offres).date() if consultation.date_limite_offres else None

    lignes = []
    offres = list(Offre.objects.filter(lot=lot).select_related("entreprise"))
    avec_base = {o.entreprise_id for o in offres if not o.variante}
    for offre in offres:
        prix, incomplete = prix_compare(offre, retenues)
        ligne = LigneClassement(offre, prix, incomplete)
        # Offres non comparables : ni notées ni classées.
        if offre.ecartee:
            ligne.motif_non_classee = f"écartée{f' : {offre.motif_ecart}' if offre.motif_ecart else ''}"
        elif limite and offre.recue_le > limite:
            ligne.motif_non_classee = "reçue après la date limite de remise des offres"
        elif offre.variante and not variantes_autorisees:
            ligne.motif_non_classee = "variante non autorisée par le règlement de la consultation"
        elif offre.montant_base is None:
            ligne.motif_non_classee = "montant non saisi"
        elif incomplete:
            ligne.motif_non_classee = "PSE retenue non chiffrée"
        elif prix is None or prix <= 0:
            ligne.motif_non_classee = "montant nul"
        ligne.variante_sans_base = offre.variante and offre.entreprise_id not in avec_base
        lignes.append(ligne)
    actives = [l for l in lignes if not l.motif_non_classee]

    if actives:
        moyenne = sum((l.prix for l in actives), Decimal("0")) / len(actives)
        minimum = min(l.prix for l in actives)
        for ligne in actives:
            ligne.ecart_moyenne = _arrondi((ligne.prix - moyenne) / moyenne * 100, "0.1")
            if montant_estimation:
                ligne.ecart_estimation = _arrondi((ligne.prix - montant_estimation) / montant_estimation * 100, "0.1")
            # Offre nettement sous la moyenne des offres (ou de l'estimation) : précisions à demander.
            seuil = Decimal(100 - analyse.seuil_anormal) / 100
            sous_moyenne = len(actives) > 1 and ligne.prix < moyenne * seuil
            sous_estimation = bool(montant_estimation) and ligne.prix < montant_estimation * seuil
            ligne.anormalement_basse = sous_moyenne or sous_estimation
            for critere in liste_criteres:
                cle = critere["libelle"]
                if critere["prix"]:
                    if analyse.methode_prix == MethodePrix.LINEAIRE:
                        note = bareme * max(Decimal("0"), 1 - (ligne.prix - minimum) / minimum)
                    else:
                        note = bareme * minimum / ligne.prix
                    ligne.notes[cle] = _arrondi(note)
                else:
                    saisie = (ligne.offre.notes.get(cle) or {}).get("note")
                    ligne.notes[cle] = None if saisie in (None, "") else Decimal(str(saisie))
                    if ligne.notes[cle] is None:
                        ligne.notation_complete = False
            if liste_criteres:
                ligne.total = _arrondi(sum(
                    ((ligne.notes[c["libelle"]] or Decimal("0")) / bareme * c["ponderation"] for c in liste_criteres), Decimal("0")
                ))
        classees = sorted((l for l in actives if l.total is not None), key=lambda l: (-l.total, l.prix))
        for rang, ligne in enumerate(classees, start=1):
            ligne.rang = rang
    return analyse, [{"libelle": c["libelle"], "ponderation": c["ponderation"], "prix": c["prix"]} for c in liste_criteres], lignes


def proposition(analyse: AnalyseLot, lignes: list[LigneClassement]) -> tuple[LigneClassement | None, bool]:
    """Offre proposée : celle choisie par l'économiste si elle est classée, sinon la mieux classée.

    Le second élément indique qu'un choix enregistré ne vaut plus (offre écartée, devenue incomplète…).
    """
    classees = sorted((l for l in lignes if l.rang), key=lambda l: l.rang)
    choisie = next((l for l in classees if l.offre.pk == analyse.attributaire_id), None)
    return choisie or (classees[0] if classees else None), bool(analyse.attributaire_id and choisie is None)


def invalider_validation(lot: LotProjet) -> None:
    """Le classement ou le choix a changé : la proposition validée est à valider de nouveau."""
    if AnalyseLot.objects.filter(lot=lot, validee_le__isnull=False).update(validee_le=None):
        ConsultationEntreprise.objects.filter(
            lot=lot, statut__in=[StatutConsultation.RETENUE, StatutConsultation.NON_RETENUE],
            entreprise_id__in=Offre.objects.filter(lot=lot).values("entreprise_id"),
        ).update(statut=StatutConsultation.REPONDU)
