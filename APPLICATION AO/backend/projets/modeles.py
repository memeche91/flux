"""Modèles de pièces administratives : modèles de base fournis avec l'application
(rédigés puis vérifiés juridiquement) et modèles enregistrés par le cabinet."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .models import ModelePiece

FICHIER_MODELES_DE_BASE = Path(__file__).parent / "modeles" / "modeles_de_base.json"


@lru_cache(maxsize=1)
def modeles_de_base() -> tuple[dict, ...]:
    if not FICHIER_MODELES_DE_BASE.exists():
        return ()
    donnees = json.loads(FICHIER_MODELES_DE_BASE.read_text(encoding="utf-8"))
    return tuple(
        {
            "id": f"base-{m['type']}-{m['marche']}",
            "nom": m["titre"],
            "type_piece": m["type"],
            "marche": m["marche"],
            "origine": "BASE",
            "clauses": m["clauses"],
        }
        for m in donnees["modeles"]
    )


def lister_modeles(type_piece: str | None = None) -> list[dict]:
    modeles = list(modeles_de_base())
    modeles += [
        {"id": f"cabinet-{m.pk}", "nom": m.nom, "type_piece": m.type_piece, "marche": m.marche, "origine": "CABINET", "clauses": m.clauses}
        for m in ModelePiece.objects.all()
    ]
    return [m for m in modeles if type_piece is None or m["type_piece"] == type_piece]


def obtenir_modele(identifiant: str) -> dict | None:
    return next((m for m in lister_modeles() if m["id"] == identifiant), None)
