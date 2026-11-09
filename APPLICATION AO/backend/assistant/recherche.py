"""Recherche des extraits utiles à une question : par le sens (plongements) et par les mots."""
from __future__ import annotations

import re
import threading
from urllib.parse import quote
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median

import numpy as np
from django.conf import settings
from django.db.models import Max

from articles.models import LignePrix
from articles.normalisation import normaliser
from projets.modeles import lister_modeles

from . import ollama
from .indexation import vers_octets
from .models import Passage, SourcePassage
from .textes import mots_cles, tronquer

QUESTION_PRIX = re.compile(r"\b(prix|co[uû]ts?|tarifs?|combien|estim\w*|chiffr\w*|budget|ratio|€|euros?|m[ée]dian\w*|montants?)\b", re.IGNORECASE)
SCORE_MINIMUM = 0.42
MAX_PAR_DOCUMENT = 3


@dataclass
class Extrait:
    passage: Passage
    score: float
    statistiques: dict | None = None
    numero: int = 0
    lignes: list[dict] = field(default_factory=list)


class _Index:
    """Matrice des plongements gardée en mémoire tant que l'index ne change pas."""

    def __init__(self):
        self._verrou = threading.Lock()
        self._version = None
        self.identifiants = np.zeros(0, dtype=np.int64)
        self.matrice = np.zeros((0, 0), dtype=np.float32)

    def charger(self):
        passages = Passage.objects.filter(modele=settings.IA_MODELE_EMBEDDING, vecteur__isnull=False)
        version = (passages.count(), passages.aggregate(Max("maj_le"))["maj_le__max"], settings.IA_MODELE_EMBEDDING)
        with self._verrou:
            if version != self._version:
                identifiants, vecteurs = [], []
                for pk, vecteur in passages.values_list("pk", "vecteur").iterator(chunk_size=2000):
                    identifiants.append(pk)
                    vecteurs.append(np.frombuffer(bytes(vecteur), dtype=np.float32))
                self.identifiants = np.asarray(identifiants, dtype=np.int64)
                self.matrice = np.vstack(vecteurs) if vecteurs else np.zeros((0, 0), dtype=np.float32)
                self._version = version
            return self.identifiants, self.matrice


INDEX = _Index()


def statistiques_prix(meta: dict) -> tuple[dict | None, list[dict]]:
    lignes = list(
        LignePrix.objects.filter(
            designation_normalisee__in=meta.get("designations", []),
            unite_normalisee=meta.get("unite", ""),
            prix_unitaire__gt=0,
        )
        .select_related("document")
        .order_by("-document__annee", "-document__ajoute_le")[:200]
    )
    if not lignes:
        return None, []
    prix = [ligne.prix_unitaire for ligne in lignes]
    details = [
        {
            "document": ligne.document.nom_original,
            "operation": ligne.document.operation,
            "annee": ligne.document.annee,
            "chapitre": ligne.chapitre,
            "prix": float(ligne.prix_unitaire),
        }
        for ligne in lignes[:6]
    ]
    return {
        "unite": lignes[0].unite or meta.get("unite", ""),
        "nombre": len(prix),
        "mediane": float(median(prix)),
        "minimum": float(min(prix)),
        "maximum": float(max(prix)),
    }, details


def rechercher(question: str, *, nombre: int = 6) -> list[Extrait]:
    identifiants, matrice = INDEX.charger()
    if not len(identifiants):
        return []
    requete = np.frombuffer(vers_octets(ollama.vectoriser([question])[0]), dtype=np.float32)
    if requete.shape[0] != matrice.shape[1]:
        return []
    scores = matrice @ requete
    meilleurs = np.argsort(-scores)[:80]
    candidats = {p.pk: p for p in Passage.objects.filter(pk__in=identifiants[meilleurs].tolist())}
    # Un modèle du cabinet supprimé depuis la dernière indexation n'est plus cité.
    modeles_existants = {m["id"] for m in lister_modeles()}
    candidats = {
        pk: p for pk, p in candidats.items() if p.source != SourcePassage.MODELE or p.meta.get("modele_id") in modeles_existants
    }

    # Bonus lexical : les mots exacts de la question (référence, matériau, unité) départagent.
    mots = set(mots_cles(question))
    notes = []
    for indice in meilleurs:
        passage = candidats.get(int(identifiants[indice]))
        if passage is None:
            continue
        score = float(scores[indice])
        if mots:
            presents = mots & set(normaliser(passage.texte).split())
            score += 0.08 * len(presents) / len(mots)
        notes.append((score, passage))
    notes.sort(key=lambda element: -element[0])

    question_prix = bool(QUESTION_PRIX.search(question))
    quotas = {SourcePassage.PRIX: 4 if question_prix else 1, SourcePassage.ARTICLE: nombre, SourcePassage.MODELE: 4}
    par_document: dict[object, int] = {}
    retenus: list[Extrait] = []
    for score, passage in notes:
        if score < SCORE_MINIMUM or len(retenus) >= nombre + (3 if question_prix else 0):
            break
        if quotas[passage.source] <= 0:
            continue
        cle_document = passage.meta.get("document_id") or passage.meta.get("modele_id") or passage.cle
        if par_document.get(cle_document, 0) >= MAX_PAR_DOCUMENT:
            continue
        extrait = Extrait(passage, score)
        if passage.source == SourcePassage.PRIX:
            extrait.statistiques, extrait.lignes = statistiques_prix(passage.meta)
            if extrait.statistiques is None:
                continue
        quotas[passage.source] -= 1
        par_document[cle_document] = par_document.get(cle_document, 0) + 1
        retenus.append(extrait)
    for numero, extrait in enumerate(retenus, start=1):
        extrait.numero = numero
    return retenus


def _euros(valeur: float) -> str:
    texte = f"{Decimal(str(valeur)).quantize(Decimal('0.01')):,.2f}".replace(",", " ").replace(".", ",")
    return f"{texte} €"


def _provenance(meta: dict) -> str:
    morceaux = [meta.get("document", "")]
    details = ", ".join(str(x) for x in [meta.get("operation"), meta.get("annee")] if x)
    if details:
        morceaux.append(f"({details})")
    return " ".join(x for x in morceaux if x)


def formater_extrait(extrait: Extrait) -> str:
    passage, meta = extrait.passage, extrait.passage.meta
    if passage.source == SourcePassage.PRIX:
        s = extrait.statistiques
        sources = " ; ".join(
            f"{d['document']}{' ' + str(d['annee']) if d['annee'] else ''}{' (' + d['chapitre'] + ')' if d.get('chapitre') else ''} : {_euros(d['prix'])}"
            for d in extrait.lignes[:4]
        )
        return (
            f"[{extrait.numero}] Prix relevés dans les DPGF du cabinet pour « {passage.titre} » (unité {s['unite']}) : "
            f"médiane {_euros(s['mediane'])} HT, minimum {_euros(s['minimum'])}, maximum {_euros(s['maximum'])}, "
            f"{s['nombre']} prix. Détail : {sources}."
        )
    if passage.source == SourcePassage.MODELE:
        return f"[{extrait.numero}] Modèle « {meta.get('modele')} » – {tronquer(passage.texte, 800)}"
    lot = f" · lot {meta['lot']}" if meta.get("lot") else ""
    return f"[{extrait.numero}] Document du cabinet « {_provenance(meta)} »{lot} – {tronquer(passage.texte, 800)}"


def source_pour_interface(extrait: Extrait) -> dict:
    passage, meta = extrait.passage, extrait.passage.meta
    commun = {"numero": extrait.numero, "type": passage.source, "titre": passage.titre}
    if passage.source == SourcePassage.PRIX:
        s = extrait.statistiques
        return {
            **commun,
            "detail": f"Médiane {_euros(s['mediane'])} HT / {s['unite']} · {s['nombre']} prix",
            "lien": f"/prix?q={quote(passage.titre[:80])}",
        }
    if passage.source == SourcePassage.MODELE:
        origine = "Modèle de base" if meta.get("origine") == "BASE" else "Modèle du cabinet"
        return {**commun, "detail": f"{origine} · {meta.get('modele', '')}", "lien": ""}
    return {
        **commun,
        "detail": _provenance(meta) + (f" · lot {meta['lot']}" if meta.get("lot") else ""),
        "lien": f"/articles?type={meta.get('type_document', '')}&document={meta.get('document_id', '')}",
    }
