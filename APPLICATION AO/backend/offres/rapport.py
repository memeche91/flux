"""Rapport d'analyse des offres (mission ACT) : même gabarit que les pièces écrites (Word et PDF)."""
from __future__ import annotations

from decimal import Decimal
from html import escape

from projets.champs import champs_du_projet
from projets.exports.document import ChapitreDoc, DocumentExport, ElementDoc
from projets.models import LotProjet, Projet

from .notation import classer, estimation


def _euros(valeur) -> str:
    if valeur in (None, ""):
        return "—"
    return f"{Decimal(str(valeur)):,.2f}".replace(",", " ").replace(".", ",") + " €"


def _pourcentage(valeur) -> str:
    if valeur is None:
        return "—"
    signe = "+" if valeur > 0 else ""
    return f"{signe}{valeur}".replace(".", ",") + " %"


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


def analyse_lot(lot: LotProjet, numero: int) -> tuple[ChapitreDoc, dict]:
    analyse, criteres, lignes = classer(lot)
    reference = estimation(lot)
    retenues = list(analyse.options_retenues.order_by("genre", "numero"))
    options = list(lot.options.all())
    chapitre = ChapitreDoc(f"lot-{lot.pk}", f"Lot {lot.code} – {lot.intitule}")
    resume = {"lot": lot, "attributaire": None, "montant": None, "estimation": None}

    if not lignes:
        chapitre.html = _p("Aucune offre n'a été reçue pour ce lot.")
        return chapitre, resume

    # Offres reçues
    entetes = ["Entreprise", "Reçue le", "Solution de base HT"] + [f"{o.nom_court} HT" for o in options] + ["Observations"]
    contenu = []
    for l in lignes:
        o = l.offre
        observations = []
        if o.ecartee:
            observations.append(f"Offre écartée : {escape(o.motif_ecart or 'motif non précisé')}")
        if o.statut_lecture == "A_VERIFIER" and o.message_lecture:
            observations.append(escape(o.message_lecture))
        if o.delai_propose:
            observations.append(f"Délai proposé : {escape(o.delai_propose)}")
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
        if l.offre.ecartee:
            remarques.append("écartée")
        if l.incomplete:
            remarques.append("incomplète (PSE retenue non chiffrée) : non classée")
        if l.anormalement_basse:
            remarques.append(f"<strong>prix anormalement bas à vérifier</strong> (au moins {analyse.seuil_anormal} % sous la moyenne ou l'estimation)")
        contenu.append([escape(l.offre.nom), _euros(l.prix), _pourcentage(l.ecart_estimation), _pourcentage(l.ecart_moyenne), ", ".join(remarques) or "—"])
    texte = (
        _p(f"Les prix sont comparés sur la {base_comparaison}. Estimation du maître d'œuvre : {_euros(montant_estimation)} HT.")
        + _tableau(["Entreprise", "Prix comparé HT", "Écart à l'estimation", "Écart à la moyenne", "Observations"], contenu)
    )
    if any(l.anormalement_basse for l in lignes):
        texte += _p("Pour toute offre qui paraît anormalement basse, des précisions et justifications sont demandées à l'entreprise avant de la retenir ou de l'écarter.")
    chapitre.elements.append(ElementDoc(f"lot-{lot.pk}-prix", f"{numero}.2 Analyse des prix", texte))

    # Analyse technique (critères autres que le prix)
    autres = [c for c in criteres if not c["prix"]]
    if autres:
        texte = ""
        for critere in autres:
            contenu = []
            for l in lignes:
                if l.offre.ecartee:
                    continue
                saisie = l.offre.notes.get(critere["libelle"]) or {}
                contenu.append([escape(l.offre.nom), f"{_note(l.notes.get(critere['libelle']))} / {analyse.bareme}", escape(saisie.get("commentaire") or "—")])
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

    # Proposition
    attributaire = next((l for l in lignes if analyse.attributaire_id and l.offre.pk == analyse.attributaire_id), None) or (classees[0] if classees else None)
    if attributaire is not None:
        taux = lot.projet.taux_tva
        ttc = (attributaire.prix or Decimal("0")) * (1 + taux / 100)
        texte = _p(
            f"Au vu de l'analyse, il est proposé de retenir l'offre de {attributaire.offre.nom} pour un montant de "
            f"{_euros(attributaire.prix)} HT, soit {_euros(ttc)} TTC (TVA {_nombre(taux)} %)"
            + (f", PSE retenues comprises ({', '.join(o.nom_court for o in retenues)})." if retenues else ".")
        )
        if analyse.observations:
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
        contenu, total, total_estimation = [], Decimal("0"), Decimal("0")
        for r in resumes:
            ecart = "—"
            if r["montant"] is not None and r["estimation"]:
                ecart = _pourcentage(((r["montant"] - r["estimation"]) / r["estimation"] * 100).quantize(Decimal("0.1")))
                total += r["montant"]
                total_estimation += r["estimation"]
            contenu.append([f"Lot {r['lot'].code} – {escape(r['lot'].intitule)}", escape(r["attributaire"] or "—"), _euros(r["montant"]), _euros(r["estimation"]), ecart])
        taux = projet.taux_tva
        texte = _tableau(["Lot", "Entreprise proposée", "Montant HT", "Estimation HT", "Écart"], contenu) + _p(
            f"Total des lots attribués : {_euros(total)} HT, soit {_euros(total * (1 + taux / 100))} TTC, "
            f"pour une estimation de {_euros(total_estimation)} HT."
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
