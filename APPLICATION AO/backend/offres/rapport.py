"""Rapport d'analyse des offres (mission ACT) : même gabarit que les pièces écrites (Word et PDF)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from html import escape

from django.utils import timezone

from projets.champs import champs_du_projet, consultation_du_projet
from projets.exports.document import ChapitreDoc, DocumentExport, ElementDoc
from projets.models import LotProjet, Projet

from .models import JustificationPrix
from .notation import classer, estimation, proposition


def _euros(valeur) -> str:
    if valeur in (None, ""):
        return "—"
    montant = Decimal(str(valeur)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)  # arrondi commercial, comme à l'écran
    return f"{montant:,.2f}".replace(",", " ").replace(".", ",") + " €"


def _pourcentage(valeur) -> str:
    if valeur is None:
        return "—"
    signe = "+" if valeur > 0 else ""
    return f"{signe}{_nombre(valeur)} %"


def _tableau(entetes: list[str], lignes: list[list[str]]) -> str:
    tete = "".join(f"<th><p>{escape(e)}</p></th>" for e in entetes)
    corps = "".join("<tr>" + "".join(f"<td><p>{c}</p></td>" for c in ligne) + "</tr>" for ligne in lignes)
    return f"<table><tbody><tr>{tete}</tr>{corps}</tbody></table>"


def _p(texte: str) -> str:
    return f"<p>{escape(texte)}</p>"


def _nombre(valeur) -> str:
    """20 → « 20 », 7.50 → « 7,5 » (sans notation scientifique ni zéros inutiles)."""
    texte = f"{Decimal(str(valeur)):f}"
    if "." in texte:
        texte = texte.rstrip("0").rstrip(".")
    return texte.replace(".", ",")


def _note(valeur) -> str:
    return "—" if valeur is None else _nombre(valeur)


def _ttc(montant: Decimal, taux: Decimal) -> Decimal:
    return (montant * (1 + taux / 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _avis_prix_bas(ligne) -> str:
    """Suite donnée à une offre qui paraît anormalement basse."""
    o = ligne.offre
    if o.justification_prix == JustificationPrix.ACCEPTEE:
        return "prix nettement inférieur aux autres offres ou à l'estimation : justifications demandées et jugées satisfaisantes" + (
            f" ({escape(o.motif_justification)})" if o.motif_justification else ""
        )
    if o.justification_prix == JustificationPrix.REJETEE:
        return "offre anormalement basse : justifications jugées insuffisantes" + (f" ({escape(o.motif_justification)})" if o.motif_justification else "")
    if o.justification_prix == JustificationPrix.DEMANDEE:
        return "<strong>prix paraissant anormalement bas : précisions demandées à l'entreprise</strong>"
    return "<strong>prix paraissant anormalement bas : précisions à demander à l'entreprise</strong>"


def analyse_lot(lot: LotProjet, numero: int) -> tuple[ChapitreDoc, dict]:
    analyse, criteres, lignes = classer(lot)
    reference = estimation(lot)
    retenues = list(analyse.options_retenues.order_by("genre", "numero"))
    options = list(lot.options.all())
    public = lot.projet.type_marche == "PUBLIC"
    limite = consultation_du_projet(lot.projet).date_limite_offres
    limite = timezone.localtime(limite).date() if limite else None
    chapitre = ChapitreDoc(f"lot-{lot.pk}", f"Lot {lot.code} – {lot.intitule}")
    resume = {"lot": lot, "attributaire": None, "montant": None, "estimation": None}

    if not lignes:
        chapitre.html = _p("Aucune offre n'a été reçue pour ce lot.")
        return chapitre, resume

    # Offres reçues : observations rédigées par l'économiste (pas les messages techniques de lecture).
    entetes = ["Entreprise", "Reçue le", "Solution de base HT"] + [f"{o.nom_court} HT" for o in options] + ["Observations"]
    contenu = []
    for l in lignes:
        o = l.offre
        observations = []
        if o.ecartee:
            observations.append(f"Offre écartée : {escape(o.motif_ecart or 'motif non précisé')}")
        elif l.motif_non_classee.startswith("variante non autorisée"):
            observations.append("Variante non autorisée par le règlement de la consultation : non examinée")
        if limite and o.recue_le > limite:
            observations.append("Reçue après la date limite de remise des offres : non examinée")
        if l.variante_sans_base:
            observations.append("Variante remise sans offre de base")
        if o.delai_propose:
            observations.append(f"Délai proposé : {escape(o.delai_propose)}")
        if o.commentaire:
            observations.append(escape(o.commentaire))
        contenu.append(
            [escape(o.nom), o.recue_le.strftime("%d/%m/%Y"), _euros(o.montant_base)]
            + [_euros(o.montants_options.get(str(opt.pk))) for opt in options]
            + ["<br>".join(observations) or "—"]
        )
    texte = _p(f"{len(lignes)} offre(s) reçue(s) pour ce lot.") + _tableau(entetes, contenu)
    chapitre.elements.append(ElementDoc(f"lot-{lot.pk}-offres", f"{numero}.1 Offres reçues", texte))

    # Analyse des prix
    montant_estimation = reference["base"] + sum((reference["options"].get(o.pk, Decimal("0")) for o in retenues), Decimal("0"))
    base_comparaison = "solution de base" + (f" et {', '.join(o.nom_court for o in retenues)}" if retenues else "")
    contenu = []
    for l in sorted(lignes, key=lambda x: (x.prix is None, x.prix or 0)):
        remarques = []
        if l.motif_non_classee:
            remarques.append(f"non classée : {escape(l.motif_non_classee)}")
        if l.anormalement_basse:
            remarques.append(_avis_prix_bas(l))
        contenu.append([escape(l.offre.nom), _euros(l.prix), _pourcentage(l.ecart_estimation), _pourcentage(l.ecart_moyenne), ", ".join(remarques) or "—"])
    texte = (
        _p(
            f"Les prix sont comparés sur la {base_comparaison}. Estimation du maître d'œuvre : "
            + (f"{_euros(montant_estimation)} HT." if montant_estimation else "non établie (DPGF sans prix estimés).")
        )
        + _tableau(["Entreprise", "Prix comparé HT", "Écart à l'estimation", "Écart à la moyenne", "Observations"], contenu)
    )
    en_suspens = [l for l in lignes if l.anormalement_basse and l.offre.justification_prix not in (JustificationPrix.ACCEPTEE, JustificationPrix.REJETEE)]
    if en_suspens:
        texte += _p(
            f"Une offre paraît anormalement basse lorsque son prix est inférieur de plus de {analyse.seuil_anormal} % à la moyenne des offres "
            "ou à l'estimation. L'entreprise est invitée à fournir des précisions et justifications sur le montant de son offre"
            + (" (articles R2152-3 à R2152-5 du code de la commande publique)" if public else "")
            + " ; l'offre n'est retenue que si ses justifications sont jugées satisfaisantes."
        )
    chapitre.elements.append(ElementDoc(f"lot-{lot.pk}-prix", f"{numero}.2 Analyse des prix", texte))

    # Analyse technique (critères autres que le prix)
    autres = [c for c in criteres if not c["prix"]]
    if autres:
        texte = ""
        for critere in autres:
            contenu = []
            for l in lignes:
                if l.motif_non_classee and not l.rang and (l.offre.ecartee or l.motif_non_classee.startswith("variante")):
                    continue
                saisie = l.offre.notes.get(critere["libelle"]) or {}
                note = l.notes.get(critere["libelle"], saisie.get("note"))
                contenu.append([escape(l.offre.nom), f"{_note(note)} / {analyse.bareme}", escape(saisie.get("commentaire") or "—")])
            texte += f"<p><strong>{escape(critere['libelle'])}</strong> ({_nombre(critere['ponderation'])} %)</p>" + _tableau(["Entreprise", "Note", "Appréciation"], contenu)
        chapitre.elements.append(ElementDoc(f"lot-{lot.pk}-technique", f"{numero}.3 Analyse technique", texte))

    # Classement
    classees = sorted((l for l in lignes if l.rang), key=lambda l: l.rang)
    if criteres and classees:
        entetes = ["Rang", "Entreprise"] + [f"{c['libelle']} ({_nombre(c['ponderation'])} %)" for c in criteres] + ["Total / 100"]
        contenu = [
            [str(l.rang), escape(l.offre.nom)] + [f"{_note(l.notes.get(c['libelle']))} / {analyse.bareme}" for c in criteres] + [f"<strong>{_note(l.total)}</strong>"]
            for l in classees
        ]
        methode = "proportionnelle (prix le plus bas / prix de l'offre)" if analyse.methode_prix == "PROPORTIONNELLE" else "linéaire (écart au prix le plus bas)"
        texte = _p(f"Notes sur {analyse.bareme}, pondérées selon le règlement de la consultation. Note du prix : méthode {methode}.") + _tableau(entetes, contenu)
        if any(not l.notation_complete for l in classees):
            texte += _p("Attention : certaines notes ne sont pas encore saisies ; elles comptent pour zéro dans ce classement.")
        chapitre.elements.append(ElementDoc(f"lot-{lot.pk}-classement", f"{numero}.4 Classement des offres", texte))

    # Proposition : seule une offre classée peut être proposée.
    attributaire, perime = proposition(analyse, lignes)
    if attributaire is not None:
        taux = lot.projet.taux_tva
        texte = _p(
            f"Au vu de l'analyse, il est proposé de retenir l'offre de {attributaire.offre.nom} pour un montant de "
            f"{_euros(attributaire.prix)} HT, soit {_euros(_ttc(attributaire.prix, taux))} TTC (TVA {_nombre(taux)} %)"
            + (f", {', '.join(o.nom_court for o in retenues)} comprise(s)." if retenues else ".")
        )
        if perime:
            choisie = next((l for l in lignes if l.offre.pk == analyse.attributaire_id), None)
            if choisie is not None:
                texte = (
                    f"<p><strong>{escape(f'L’offre choisie ({choisie.offre.nom}) n’est plus classée ({choisie.motif_non_classee or 'notation incomplète'}) : proposition à revoir.')}</strong></p>"
                    + texte
                )
        if attributaire.rang and attributaire.rang > 1:
            texte += _p(f"Cette offre est classée {attributaire.rang}e" + (" : le choix est motivé dans les observations ci-dessous." if analyse.observations.strip() else "."))
        if attributaire.anormalement_basse:
            if attributaire.offre.justification_prix == JustificationPrix.ACCEPTEE:
                texte += _p(
                    "Son prix, nettement inférieur à la moyenne des offres ou à l'estimation, a fait l'objet d'une demande de précisions ; "
                    "les justifications apportées par l'entreprise ont été jugées satisfaisantes"
                    + (f" : {attributaire.offre.motif_justification}" if attributaire.offre.motif_justification else ".")
                )
            else:
                texte += f"<p><strong>{escape('Réserve : le prix de cette offre paraît anormalement bas ; elle ne pourra être retenue qu’après examen des justifications demandées à l’entreprise.')}</strong></p>"
        if analyse.observations and not perime:  # observations écrites pour l'offre choisie
            texte += "".join(_p(p) for p in analyse.observations.split("\n") if p.strip())
        chapitre.elements.append(ElementDoc(f"lot-{lot.pk}-proposition", f"{numero}.5 Proposition d'attribution", texte))
        resume.update(attributaire=attributaire.offre.nom, montant=attributaire.prix, estimation=montant_estimation)
    return chapitre, resume


def document_rapport(projet: Projet, lots: list[LotProjet] | None = None) -> DocumentExport:
    lots = lots or list(projet.lots.order_by("ordre", "code"))
    champs = champs_du_projet(projet)
    valeur = lambda cle: champs[cle].apercu if champs.get(cle) and champs[cle].renseigne else "non renseigné(e)"  # noqa: E731

    chapitres = [
        ChapitreDoc("objet", "Objet du rapport", _p(
            f"Le présent rapport présente l'analyse des offres reçues pour l'opération « {projet.nom} »"
            + (f" ({projet.maitre_ouvrage})" if projet.maitre_ouvrage else "")
            + ", ainsi que la proposition d'attribution établie par la maîtrise d'œuvre selon les critères du règlement de la consultation."
        )),
    ]
    criteres_html = champs["criteres_jugement"].valeur if champs.get("criteres_jugement") and champs["criteres_jugement"].renseigne else _p("Critères non renseignés.")
    chapitres.append(ChapitreDoc("rappel", "Rappel de la consultation", (
        _p(f"Procédure : {valeur('procedure')}.")
        + _p(f"Date limite de remise des offres : {valeur('date_limite_offres')}.")
        + _p("Critères de jugement des offres :") + criteres_html
    )))

    resumes = []
    for numero, lot in enumerate(lots, start=3):
        chapitre, resume = analyse_lot(lot, numero)
        chapitres.append(chapitre)
        resumes.append(resume)

    if len(lots) > 1:
        contenu, total, total_estimation, estimation_partielle = [], Decimal("0"), Decimal("0"), False
        for r in resumes:
            ecart = "—"
            if r["montant"] is not None:
                total += r["montant"]
                if r["estimation"]:
                    ecart = _pourcentage(((r["montant"] - r["estimation"]) / r["estimation"] * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
                    total_estimation += r["estimation"]
                else:
                    estimation_partielle = True
            estimation_lot = _euros(r["estimation"]) if r["estimation"] else ("non établie" if r["montant"] is not None else "—")
            contenu.append([f"Lot {r['lot'].code} – {escape(r['lot'].intitule)}", escape(r["attributaire"] or "—"), _euros(r["montant"]), estimation_lot, ecart])
        taux = projet.taux_tva
        texte = _tableau(["Lot", "Entreprise proposée", "Montant HT", "Estimation HT", "Écart"], contenu) + _p(
            f"Total des lots attribués : {_euros(total)} HT, soit {_euros(_ttc(total, taux))} TTC"
            + (f", pour une estimation de {_euros(total_estimation)} HT" if total_estimation else "")
            + (" (estimation non établie pour certains lots)." if estimation_partielle and total_estimation else ".")
        )
        chapitres.append(ChapitreDoc("recapitulatif", "Récapitulatif général", texte))

    seul = lots[0] if len(lots) == 1 else None
    return DocumentExport(
        projet=projet,
        titre_piece="Rapport d'analyse des offres",
        sigle="ACT",
        sous_titre=f"Lot {seul.code} – {seul.intitule}" if seul else "Tous les lots",
        pied=f"{projet.nom} – Rapport d'analyse des offres" + (f" – lot {seul.code}" if seul else ""),
        nom_fichier=f"Rapport d'analyse des offres - {projet.nom}" + (f" - lot {seul.code}" if seul else ""),
        chapitres=chapitres,
    )
