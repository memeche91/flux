"""Remise des fichiers déposés (offres, GED, bibliothèque, DCE) : une seule règle sûre.

Les fichiers viennent de tiers (entreprises, Internet). Seuls PDF et images courantes sont
affichés dans le navigateur, avec un type imposé ; tout le reste est téléchargé
(application/octet-stream, pièce jointe) : un HTML, SVG ou XML n'est jamais exécuté sur
l'origine de l'application.
"""
from __future__ import annotations

from pathlib import Path

from django.http import FileResponse
from ninja.errors import HttpError

AFFICHABLES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


def reponse_fichier_sure(champ, nom: str, *, telecharger: bool = False, type_impose: str | None = None) -> FileResponse:
    if not champ:
        raise HttpError(404, "Aucun fichier.")
    try:
        flux = champ.open("rb")
    except FileNotFoundError:
        raise HttpError(410, "Fichier absent du disque (retiré par l'antivirus ou supprimé) : contactez la maîtrise d'œuvre.") from None
    extension = Path(nom).suffix.lower()
    if extension in AFFICHABLES and not telecharger:
        reponse = FileResponse(flux, content_type=AFFICHABLES[extension], as_attachment=False, filename=nom)
        if extension != ".pdf":
            reponse["Content-Security-Policy"] = "sandbox"
    else:
        reponse = FileResponse(flux, content_type=type_impose or "application/octet-stream", as_attachment=True, filename=nom)
    reponse["X-Content-Type-Options"] = "nosniff"
    return reponse
