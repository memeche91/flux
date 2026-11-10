"""Miroir d'un dossier de l'application vers le dossier des sauvegardes (fichiers gardés sur le PC).

Seuls les fichiers nouveaux ou modifiés (taille ou date différente) sont copiés. Un fichier disparu de
l'application n'est effacé de la sauvegarde qu'après DELAI_SUPPRESSION : la date de sa disparition est
notée dans un manifeste (fichier JSON rangé hors du miroir). Une suppression par erreur, ou une purge de
fin de chantier, reste ainsi récupérable pendant un mois.
"""
from __future__ import annotations

import contextlib
import datetime
import errno
import json
import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .postgres import ErreurSauvegarde

DELAI_SUPPRESSION = datetime.timedelta(days=30)
TOLERANCE_DATE = 2  # secondes : les partages Windows arrondissent parfois les dates
SUFFIXE_PARTIEL = ".partiel"


@dataclass
class BilanMiroir:
    copies: int = 0
    octets: int = 0
    en_attente: int = 0  # fichiers disparus de l'application, gardés jusqu'à la fin du délai
    supprimes: int = 0
    erreurs: list[str] = field(default_factory=list)
    suppressions_suspendues: str = ""  # motif quand la liste des fichiers n'est pas fiable


def _lister(source: Path, exclus: set[Path], erreurs: list[str]) -> dict[str, os.stat_result]:
    fichiers: dict[str, os.stat_result] = {}

    def noter(exc: OSError) -> None:
        erreurs.append(f"{exc.filename} : {exc.strerror or exc}")

    for racine, dossiers, noms in os.walk(source, onerror=noter):
        dossier = Path(racine)
        dossiers[:] = [d for d in dossiers if not (dossier / d).is_symlink() and (not exclus or (dossier / d).resolve() not in exclus)]
        for nom in noms:
            if nom.endswith(SUFFIXE_PARTIEL):  # fichier en cours d'écriture (archive en préparation…)
                continue
            chemin = dossier / nom
            try:
                etat = chemin.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                noter(exc)
                continue
            if stat.S_ISREG(etat.st_mode):
                fichiers[chemin.relative_to(source).as_posix()] = etat
    return fichiers


def _identique(cible: Path, etat: os.stat_result) -> bool:
    try:
        existant = cible.stat()
    except OSError:
        return False
    return existant.st_size == etat.st_size and abs(existant.st_mtime - etat.st_mtime) <= TOLERANCE_DATE


def _copier(source: Path, cible: Path, etat: os.stat_result) -> None:
    """Copie dans un .partiel puis renomme : jamais de fichier à moitié copié sous son vrai nom."""
    cible.parent.mkdir(parents=True, exist_ok=True)
    partiel = cible.with_name(cible.name + SUFFIXE_PARTIEL)
    try:
        shutil.copyfile(source, partiel)
        with contextlib.suppress(OSError):  # date d'origine : la copie ne sera pas refaite la nuit suivante
            os.utime(partiel, ns=(etat.st_atime_ns, etat.st_mtime_ns))
        os.replace(partiel, cible)
    except BaseException:
        with contextlib.suppress(OSError):
            partiel.unlink()
        raise


def _charger(manifeste: Path) -> dict[str, str]:
    try:
        contenu = json.loads(manifeste.read_text(encoding="utf-8"))
        disparus = contenu.get("disparus", {})
        return {str(cle): str(valeur) for cle, valeur in disparus.items()} if isinstance(disparus, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}  # manifeste absent ou abîmé : le délai repart de zéro (on ne supprime rien de plus)


def _ecrire(manifeste: Path, disparus: dict[str, str], maintenant: datetime.datetime) -> None:
    manifeste.parent.mkdir(parents=True, exist_ok=True)
    partiel = manifeste.with_name(manifeste.name + SUFFIXE_PARTIEL)
    contenu = {"explication": "Fichiers disparus de l'application, effacés de la sauvegarde 30 jours après leur disparition.",
               "mis_a_jour": maintenant.isoformat(), "disparus": dict(sorted(disparus.items()))}
    partiel.write_text(json.dumps(contenu, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(partiel, manifeste)


def _date(texte: str | None) -> datetime.datetime | None:
    if not texte:
        return None
    try:
        date = datetime.datetime.fromisoformat(texte)
    except ValueError:
        return None
    return date if date.tzinfo else date.replace(tzinfo=datetime.timezone.utc)


def _suppressions_differees(destination: Path, presents: dict, manifeste: Path, maintenant: datetime.datetime,
                            bilan: BilanMiroir, fiable: bool) -> None:
    anciens = _charger(manifeste)
    disparus: dict[str, str] = {}
    for racine, _dossiers, noms in os.walk(destination):
        for nom in noms:
            chemin = Path(racine) / nom
            relatif = chemin.relative_to(destination).as_posix()
            if nom.endswith(SUFFIXE_PARTIEL):  # reste d'une copie interrompue
                with contextlib.suppress(OSError):
                    chemin.unlink()
                continue
            if relatif in presents:
                continue
            if not fiable:  # liste incomplète : on ne marque ni n'efface rien de nouveau
                if relatif in anciens:
                    disparus[relatif] = anciens[relatif]
                continue
            depuis = _date(anciens.get(relatif)) or maintenant
            if maintenant - depuis < DELAI_SUPPRESSION:
                disparus[relatif] = depuis.isoformat()
                continue
            try:
                chemin.unlink()
                bilan.supprimes += 1
            except FileNotFoundError:
                pass
            except OSError as exc:
                bilan.erreurs.append(f"{relatif} : suppression impossible ({exc.strerror or exc})")
                disparus[relatif] = depuis.isoformat()
    for racine, dossiers, noms in os.walk(destination, topdown=False):  # dossiers vidés par la suppression
        if Path(racine) != destination and not dossiers and not noms:
            with contextlib.suppress(OSError):
                Path(racine).rmdir()
    bilan.en_attente = len(disparus)
    _ecrire(manifeste, disparus, maintenant)


def miroir(source: Path, destination: Path, maintenant: datetime.datetime, manifeste: Path | None = None,
           exclus: tuple[Path, ...] = (), supprimer: bool = True,
           libelle_destination: str = "dans le dossier des sauvegardes") -> BilanMiroir:
    """Copie `source` dans `destination` ; avec `supprimer`, efface après 30 jours ce qui a disparu de `source`.

    `exclus` : dossiers à ne pas parcourir (dossier d'archives ou de sauvegardes rangé dans la source).
    `libelle_destination` : où manque la place quand le disque de `destination` est plein (message d'erreur).
    """
    bilan = BilanMiroir()
    erreurs_lecture: list[str] = []
    exclus_resolus = {chemin.resolve() for chemin in exclus if chemin}
    if source.is_dir():
        presents = _lister(source, exclus_resolus, erreurs_lecture)
    else:
        presents = {}
        bilan.suppressions_suspendues = f"dossier {source} introuvable"
    destination.mkdir(parents=True, exist_ok=True)
    for relatif, etat in presents.items():
        cible = destination / relatif
        if _identique(cible, etat):
            continue
        try:
            _copier(source / relatif, cible, etat)
        except FileNotFoundError:
            continue  # supprimé de l'application pendant la copie
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise ErreurSauvegarde(f"plus de place {libelle_destination} ({bilan.copies} fichiers copiés).") from exc
            bilan.erreurs.append(f"{relatif} : {exc.strerror or exc}")
            continue
        bilan.copies += 1
        bilan.octets += etat.st_size
    bilan.erreurs[:0] = erreurs_lecture
    if erreurs_lecture:
        bilan.suppressions_suspendues = "certains dossiers n’ont pas pu être lus"
    elif not presents and source.is_dir() and any(f for _r, _d, f in os.walk(destination)):
        # Dossier vide alors que la sauvegarde contient des fichiers : partage non monté ? Rien n'est marqué.
        bilan.suppressions_suspendues = f"dossier {source} vide"
    if supprimer and manifeste is not None:
        _suppressions_differees(destination, presents, manifeste, maintenant, bilan, fiable=not bilan.suppressions_suspendues)
    return bilan
