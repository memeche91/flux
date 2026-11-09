"""Index de recherche par le sens (plongements calculés par Ollama).

Trois sources : les articles de la bibliothèque (CCTP, CCAP, RC, AE découpés),
les prix relevés dans les DPGF (regroupés par désignation et unité) et les
clauses des modèles de pièces (modèles de base vérifiés et modèles du cabinet).
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable

import numpy as np
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from articles.models import Article, LignePrix
from articles.normalisation import normaliser
from projets.modeles import lister_modeles

from . import ollama
from .models import Passage, SourcePassage
from .textes import html_vers_texte, tronquer

logger = logging.getLogger(__name__)

LOT_INDEXATION = 16
NOMS_TYPES = {"CCTP": "CCTP", "CCAP": "CCAP", "RC": "règlement de consultation", "AE": "acte d'engagement", "DPGF": "DPGF"}


def _empreinte(texte: str) -> str:
    return hashlib.sha1(texte.encode("utf-8")).hexdigest()


def _passages_articles() -> dict[str, dict]:
    attendus = {}
    for article in Article.objects.select_related("document", "lot").iterator(chunk_size=500):
        document = article.document
        titre = f"{article.numero} {article.titre}".strip()
        entete = " › ".join(x for x in [article.chemin, titre] if x)
        attendus[f"article:{article.pk}"] = {
            "source": SourcePassage.ARTICLE,
            "article_id": article.pk,
            "titre": titre[:500],
            "texte": tronquer(f"{NOMS_TYPES.get(document.type_document, document.type_document)} – {entete}\n{article.contenu}", 1500),
            "meta": {
                "document_id": document.pk,
                "document": document.nom_original,
                "type_document": document.type_document,
                "lot": article.lot.code if article.lot else "",
                "lot_id": article.lot_id,
                "operation": document.operation,
                "annee": document.annee,
                "chemin": article.chemin,
            },
        }
    return attendus


def _passages_prix() -> dict[str, dict]:
    """Un passage par ouvrage et par unité, quel que soit le chapitre où il a été relevé."""
    groupes: dict[tuple[str, str], dict] = {}
    lignes = (
        LignePrix.objects.filter(prix_unitaire__gt=0)
        .order_by("-document__annee", "id")
        .values("designation", "designation_normalisee", "unite", "unite_normalisee", "chapitre", "lot__code")
    )
    for ligne in lignes.iterator(chunk_size=2000):
        designation = normaliser(ligne["designation"])
        if not designation:
            continue
        groupe = groupes.setdefault((designation, ligne["unite_normalisee"]), {**ligne, "normalisees": set()})
        groupe["normalisees"].add(ligne["designation_normalisee"])
    attendus = {}
    for (designation, unite), groupe in groupes.items():
        lot = f"lot {groupe['lot__code']}" if groupe["lot__code"] else ""
        texte = " – ".join(x for x in [groupe["designation"], f"unité {groupe['unite'] or unite}", groupe["chapitre"], lot] if x)
        attendus[f"prix:{_empreinte(designation + '|' + unite)}"] = {
            "source": SourcePassage.PRIX,
            "article_id": None,
            "titre": groupe["designation"][:500],
            "texte": tronquer(f"Prix unitaire : {texte}", 600),
            "meta": {"designations": sorted(groupe["normalisees"]), "unite": unite, "lot": groupe["lot__code"] or ""},
        }
    return attendus


def _passages_modeles() -> dict[str, dict]:
    attendus = {}
    for modele in lister_modeles():
        nature = "marché public" if modele["marche"] == "PUBLIC" else "marché privé"
        origine = "modèle de base vérifié" if modele["origine"] == "BASE" else "modèle du cabinet"
        chapitre = ""
        for indice, clause in enumerate(modele["clauses"]):
            contenu = html_vers_texte(clause.get("contenu", ""))
            titre = clause.get("titre", "")
            if clause.get("genre") == "CHAPITRE":
                chapitre = titre
                if not contenu:
                    continue
                entete = titre
            else:
                entete = f"{chapitre} › {titre}" if chapitre else titre
            attendus[f"modele:{modele['id']}:{indice}"] = {
                "source": SourcePassage.MODELE,
                "article_id": None,
                "titre": titre[:500],
                "texte": tronquer(f"{modele['type_piece']} ({nature}, {origine}) – {entete}\n{contenu}", 1500),
                "meta": {
                    "modele_id": modele["id"],
                    "modele": modele["nom"],
                    "type_piece": modele["type_piece"],
                    "marche": modele["marche"],
                    "origine": modele["origine"],
                    "chapitre": chapitre,
                },
            }
    return attendus


def passages_attendus() -> dict[str, dict]:
    return {**_passages_articles(), **_passages_prix(), **_passages_modeles()}


@transaction.atomic
def synchroniser() -> list[int]:
    """Met les passages en accord avec les données ; renvoie ceux dont le plongement est à calculer."""
    attendus = passages_attendus()
    existants = {p.cle: p for p in Passage.objects.all()}
    Passage.objects.filter(cle__in=set(existants) - set(attendus)).delete()

    a_creer, a_modifier = [], []
    for cle, valeurs in attendus.items():
        empreinte = _empreinte(valeurs["texte"])
        passage = existants.get(cle)
        if passage is None:
            a_creer.append(Passage(cle=cle, empreinte=empreinte, **valeurs))
        elif passage.empreinte != empreinte or passage.titre != valeurs["titre"] or passage.meta != valeurs["meta"]:
            texte_change = passage.empreinte != empreinte
            for champ, valeur in valeurs.items():
                setattr(passage, champ, valeur)
            passage.empreinte = empreinte
            if texte_change:
                passage.vecteur = None
                passage.modele = ""
            passage.maj_le = timezone.now()
            a_modifier.append(passage)
    Passage.objects.bulk_create(a_creer, batch_size=500)
    if a_modifier:
        Passage.objects.bulk_update(a_modifier, ["titre", "texte", "meta", "empreinte", "vecteur", "modele", "maj_le", "source", "article"], batch_size=500)
    a_calculer = Passage.objects.filter(Q(vecteur__isnull=True) | ~Q(modele=settings.IA_MODELE_EMBEDDING))
    # Les documents et les prix du cabinet d'abord, les modèles de pièces ensuite.
    priorite = {SourcePassage.PRIX: 0, SourcePassage.ARTICLE: 1, SourcePassage.MODELE: 2}
    return [pk for pk, _ in sorted(a_calculer.values_list("pk", "source"), key=lambda e: (priorite.get(e[1], 3), e[0]))]


def vers_octets(vecteur) -> bytes:
    tableau = np.asarray(vecteur, dtype=np.float32)
    norme = float(np.linalg.norm(tableau)) or 1.0
    return (tableau / norme).astype(np.float32).tobytes()


def calculer_plongements(identifiants: list[int], progression: Callable[[int], None] | None = None) -> int:
    faits = 0
    for debut in range(0, len(identifiants), LOT_INDEXATION):
        lot = list(Passage.objects.filter(pk__in=identifiants[debut : debut + LOT_INDEXATION]).only("pk", "texte"))
        vecteurs = ollama.vectoriser([p.texte for p in lot])
        for passage, vecteur in zip(lot, vecteurs, strict=True):
            passage.vecteur = vers_octets(vecteur)
            passage.modele = settings.IA_MODELE_EMBEDDING
        Passage.objects.bulk_update(lot, ["vecteur", "modele"])
        faits += len(lot)
        if progression:
            progression(faits)
    return faits
