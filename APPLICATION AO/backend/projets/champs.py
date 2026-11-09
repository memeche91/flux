"""Champs automatiques des pièces écrites : {{ nom_operation }}, {{ date_limite_offres }}…

Les modèles contiennent des champs entre accolades doubles ; ils sont remplacés à
l'export par les données du projet et de la consultation. Une donnée manquante
apparaît surlignée « [à compléter : …] » pour ne pas passer inaperçue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from html import escape

from django.utils import timezone
from django.utils.formats import date_format

from .models import Consultation, FormePrix, LotProjet, Projet, Visite


@dataclass
class Champ:
    cle: str
    libelle: str
    valeur: str  # HTML prêt à insérer (texte échappé ou bloc HTML construit par l'application)
    renseigne: bool
    bloc: bool = False  # liste ou tableau : remplace tout le paragraphe qui le contient

    @property
    def apercu(self) -> str:
        """Valeur en texte brut, pour l'affichage dans l'éditeur."""
        texte = re.sub(r"</(li|tr|p)>", " · ", self.valeur)
        texte = re.sub(r"<[^>]+>", "", texte)
        return " ".join(texte.replace("&nbsp;", " ").split()).strip(" ·")


CHAMP = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def _pourcentage(valeur: Decimal | int | float | None) -> str:
    if valeur is None:
        return ""
    nombre = Decimal(str(valeur)).normalize()
    texte = f"{nombre:f}".replace(".", ",")
    return f"{texte} %"


def _texte(cle: str, libelle: str, valeur: str | None) -> Champ:
    valeur = (valeur or "").strip()
    return Champ(cle, libelle, escape(valeur).replace("\n", "<br>"), bool(valeur))


def _liste(elements: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(e)}</li>" for e in elements) + "</ul>"


def consultation_du_projet(projet: Projet) -> Consultation:
    consultation, _ = Consultation.objects.get_or_create(projet=projet)
    return consultation


def champs_du_projet(projet: Projet, lot: LotProjet | None = None) -> dict[str, Champ]:
    c = consultation_du_projet(projet)
    lots = list(projet.lots.prefetch_related("options").order_by("ordre", "code"))

    champs = [
        _texte("nom_operation", "Nom de l'opération", projet.nom),
        _texte("numero_affaire", "N° d'affaire", projet.numero),
        _texte("maitre_ouvrage", "Maître d'ouvrage", projet.maitre_ouvrage),
        _texte("adresse_maitre_ouvrage", "Adresse du maître d'ouvrage", projet.adresse_maitre_ouvrage),
        _texte("adresse_operation", "Adresse de l'opération", projet.adresse_operation),
        _texte("maitre_oeuvre", "Maîtrise d'œuvre", projet.maitre_oeuvre),
        _texte("procedure", "Procédure", projet.procedure),
        _texte("date_documents", "Date des documents", date_format(projet.date_document or timezone.localdate(), "j F Y")),
        _texte("nombre_lots", "Nombre de lots", str(len(lots)) if lots else ""),
        _texte(
            "date_limite_offres",
            "Date limite de remise des offres",
            date_format(timezone.localtime(c.date_limite_offres), r"l j F Y \à H \h i") if c.date_limite_offres else "",
        ),
        _texte("duree_validite_offres", "Validité des offres", f"{c.duree_validite_offres} jours" if c.duree_validite_offres else ""),
        _texte("delai_execution", "Délai d'exécution", c.delai_execution),
        _texte("date_debut_travaux", "Démarrage prévisionnel des travaux", c.date_debut_travaux),
        _texte("visite_site", "Visite du site", _phrase_visite(c)),
        _texte("variantes", "Variantes", _phrase_variantes(c)),
        _texte("forme_prix", "Forme des prix", FormePrix(c.forme_prix).label),
        _texte("index_reference", "Index de référence", c.index_reference),
        _texte("taux_retenue_garantie", "Retenue de garantie", _pourcentage(c.taux_retenue_garantie)),
        _texte("taux_avance", "Avance", _pourcentage(c.taux_avance)),
        _texte("penalites_retard", "Pénalités de retard", c.penalites_retard),
        _texte("profil_acheteur", "Profil d'acheteur", c.profil_acheteur),
        _texte("contact_consultation", "Contact pour les questions", c.contact),
        _texte("taux_tva", "Taux de TVA", _pourcentage(projet.taux_tva)),
    ]

    liste_lots = [f"Lot {l.code} – {l.intitule}" for l in lots]
    champs.append(Champ("liste_lots", "Liste des lots", _liste(liste_lots) if lots else "", bool(lots), bloc=True))

    options = [f"Lot {l.code} – {l.intitule} : {o.nom_court} – {o.libelle}" for l in lots for o in l.options.all()]
    champs.append(
        Champ(
            "liste_pse",
            "PSE et variantes exigées",
            _liste(options) if options else "<p>Aucune prestation supplémentaire éventuelle ni variante exigée n'est prévue.</p>",
            True,
            bloc=True,
        )
    )

    criteres = [x for x in (c.criteres or []) if str(x.get("libelle", "")).strip()]
    tableau = ""
    if criteres:
        lignes = "".join(
            f"<tr><td><p>{escape(str(x['libelle']))}</p></td><td><p>{_pourcentage(x.get('ponderation', 0))}</p></td></tr>"
            for x in criteres
        )
        tableau = f"<table><tbody><tr><th><p>Critère</p></th><th><p>Pondération</p></th></tr>{lignes}</tbody></table>"
    champs.append(Champ("criteres_jugement", "Critères de jugement des offres", tableau, bool(criteres), bloc=True))

    if lot is not None:
        champs.append(_texte("lot_code", "Code du lot", lot.code))
        champs.append(_texte("lot_intitule", "Intitulé du lot", lot.intitule))
        options_lot = [f"{o.nom_court} – {o.libelle}" for o in lot.options.all()]
        champs.append(
            Champ(
                "lot_pse",
                "PSE et variantes du lot",
                _liste(options_lot) if options_lot else "<p>Aucune prestation supplémentaire éventuelle ni variante exigée pour ce lot.</p>",
                True,
                bloc=True,
            )
        )
    return {champ.cle: champ for champ in champs}


def _phrase_visite(c: Consultation) -> str:
    modalites = f" Modalités : {c.modalites_visite.strip().rstrip('.')}." if c.modalites_visite.strip() else ""
    if c.visite == Visite.OBLIGATOIRE:
        return f"La visite du site est obligatoire. Une attestation de visite est remise au candidat et jointe à son offre.{modalites}"
    if c.visite == Visite.FACULTATIVE:
        return f"La visite du site est facultative mais vivement conseillée.{modalites}"
    return "Aucune visite du site n'est organisée."


def _phrase_variantes(c: Consultation) -> str:
    if c.variantes_autorisees:
        return "Les variantes à l'initiative des candidats sont autorisées ; elles sont présentées en complément d'une offre de base, qui reste obligatoire."
    return "Les variantes à l'initiative des candidats ne sont pas autorisées."


def _a_completer(libelle: str) -> str:
    return f'<mark style="background-color: #FFE599">[à compléter : {escape(libelle)}]</mark>'


def remplacer_champs(html: str, champs: dict[str, Champ]) -> str:
    """Remplace les champs d'un texte HTML ; un champ « bloc » seul dans un paragraphe remplace ce paragraphe."""
    if not html or "{{" not in html:
        return html

    def bloc(correspondance: re.Match) -> str:
        champ = champs.get(correspondance.group(1))
        if champ is None or not champ.bloc:
            return correspondance.group(0)
        return champ.valeur if champ.renseigne else f"<p>{_a_completer(champ.libelle)}</p>"

    html = re.sub(r"<p[^>]*>\s*\{\{\s*([a-z_]+)\s*\}\}\s*</p>", bloc, html)

    def en_ligne(correspondance: re.Match) -> str:
        cle = correspondance.group(1)
        champ = champs.get(cle)
        if champ is None:
            return _a_completer(f"champ inconnu « {cle} »")
        if not champ.renseigne:
            return _a_completer(champ.libelle)
        return champ.valeur

    return CHAMP.sub(en_ligne, html)


def remplacer_dans_titre(titre: str, champs: dict[str, Champ]) -> str:
    """Version texte brut (titres) : les champs sont remplacés par leur aperçu."""
    def remplacement(correspondance: re.Match) -> str:
        champ = champs.get(correspondance.group(1))
        return champ.apercu if champ and champ.renseigne else "[à compléter]"

    return CHAMP.sub(remplacement, titre or "")


def champs_utilises(textes: list[str]) -> set[str]:
    return {m.group(1) for texte in textes for m in CHAMP.finditer(texte or "")}
