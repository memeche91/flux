"""Outils PostgreSQL 16 de la sauvegarde : pg_dump, restauration d'essai, restauration.

Les outils (pg_dump, pg_restore, createdb, dropdb, psql : paquet postgresql-client-16) sont installés dans
l'image du backend depuis le dépôt officiel PostgreSQL (même version que la base). Le mot de passe passe
par PGPASSWORD, jamais par la ligne de commande : il n'apparaît ni dans la liste des processus ni dans
les messages.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

BASE_ESSAI = "verification_sauvegarde"
DELAI_OUTIL = 3 * 3600  # secondes accordées à chaque outil (grosse base, disque lent)


class ErreurSauvegarde(Exception):
    """Erreur expliquée à l'administrateur (message en français, sans secret)."""


def parametres() -> dict:
    base = settings.DATABASES["default"]
    if "postgresql" not in base["ENGINE"]:
        raise ErreurSauvegarde("la sauvegarde de la base nécessite PostgreSQL (application lancée par Docker).")
    return {
        "dbname": base["NAME"], "user": base["USER"], "password": base.get("PASSWORD") or "",
        "host": base["HOST"], "port": str(base.get("PORT") or "5432"),
    }


def _environnement(p: dict) -> dict:
    env = {cle: valeur for cle, valeur in os.environ.items() if not cle.startswith("PG")}
    env.update({"PGHOST": p["host"], "PGPORT": p["port"], "PGUSER": p["user"], "PGPASSWORD": p["password"], "PGCONNECT_TIMEOUT": "30"})
    return env


def _extrait(texte: str, longueur: int = 400) -> str:
    lignes = [ligne.strip() for ligne in (texte or "").splitlines() if ligne.strip()]
    return " ".join(lignes)[-longueur:] or "aucun détail"


def executer(commande: list[str], p: dict, delai: int = DELAI_OUTIL) -> str:
    try:
        resultat = subprocess.run(
            commande, env=_environnement(p), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=delai, check=False,
        )
    except FileNotFoundError as exc:
        raise ErreurSauvegarde(f"outil « {commande[0]} » absent de l’application : reconstruisez-la avec installer.ps1.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ErreurSauvegarde(f"« {commande[0]} » n’a pas terminé en {delai // 60} minutes.") from exc
    if resultat.returncode != 0:
        raise ErreurSauvegarde(f"« {commande[0]} » a échoué : {_extrait(resultat.stderr)}")
    return resultat.stdout


def connexion(p: dict, base: str | None = None):
    import psycopg

    try:
        return psycopg.connect(
            dbname=base or p["dbname"], user=p["user"], password=p["password"], host=p["host"], port=p["port"],
            connect_timeout=30, application_name="sauvegarde",
        )
    except psycopg.Error as exc:
        raise ErreurSauvegarde(f"base de données injoignable ({_extrait(str(exc), 200)}).") from exc


def _compter(curseur) -> dict[str, int]:
    """Nombre de lignes de chaque table de l'application (schéma public)."""
    from psycopg import sql

    curseur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
    comptes = {}
    for (table,) in curseur.fetchall():
        curseur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("public", table)))
        comptes[table] = curseur.fetchone()[0]
    return comptes


@contextlib.contextmanager
def instantane(p: dict):
    """Ouvre une transaction figée sur la base et donne (identifiant d'instantané, lignes par table).

    pg_dump lancé avec cet instantané copie exactement l'état compté ici : la restauration d'essai doit
    retrouver les mêmes nombres, même si quelqu'un travaille dans l'application pendant la sauvegarde.
    """
    import psycopg

    with connexion(p) as liaison:
        try:
            liaison.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            with liaison.cursor() as curseur:
                curseur.execute("SELECT pg_export_snapshot()")
                identifiant = curseur.fetchone()[0]
                comptes = _compter(curseur)
        except psycopg.Error as exc:
            raise ErreurSauvegarde(f"lecture de la base impossible ({_extrait(str(exc), 200)}).") from exc
        yield identifiant, comptes
        liaison.rollback()


def compter_base(p: dict, base: str) -> dict[str, int]:
    import psycopg

    with connexion(p, base) as liaison:
        try:
            with liaison.cursor() as curseur:
                return _compter(curseur)
        except psycopg.Error as exc:
            raise ErreurSauvegarde(f"lecture de la base {base} impossible ({_extrait(str(exc), 200)}).") from exc


def exporter(destination: Path, p: dict) -> dict[str, int]:
    """pg_dump au format personnalisé (compressé) dans `destination` ; renvoie les lignes par table."""
    with instantane(p) as (identifiant, comptes):
        executer(["pg_dump", "--format=custom", f"--snapshot={identifiant}", f"--file={destination}", p["dbname"]], p)
    return comptes


def _supprimer_base_essai(p: dict) -> None:
    executer(["dropdb", "--if-exists", "--force", f"--maintenance-db={p['dbname']}", BASE_ESSAI], p)


def verifier(fichier: Path, p: dict, attendus: dict[str, int]) -> tuple[int, int]:
    """Restauration d'essai dans une base temporaire, puis comparaison des lignes de chaque table.

    Renvoie (tables, lignes) ; lève ErreurSauvegarde si la copie ne se restaure pas à l'identique.
    """
    _supprimer_base_essai(p)  # reste d'un essai interrompu
    executer(["createdb", "--template=template0", f"--maintenance-db={p['dbname']}", BASE_ESSAI], p)
    try:
        executer(["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error", f"--dbname={BASE_ESSAI}", str(fichier)], p)
        obtenus = compter_base(p, BASE_ESSAI)
    finally:
        with contextlib.suppress(ErreurSauvegarde):
            _supprimer_base_essai(p)
    manquantes = sorted(set(attendus) - set(obtenus))
    ecarts = [f"{table} ({obtenus[table]} lignes au lieu de {attendus[table]})"
              for table in sorted(attendus) if table in obtenus and obtenus[table] != attendus[table]]
    if manquantes or ecarts:
        details = ([f"tables absentes : {', '.join(manquantes[:5])}"] if manquantes else []) + ecarts[:5]
        raise ErreurSauvegarde("la copie restaurée ne correspond pas à la base (" + " ; ".join(details) + ").")
    return len(attendus), sum(attendus.values())


def restaurer(fichier: Path, p: dict) -> None:
    """Remplace le contenu de la base de l'application par la copie (tout ou rien : une seule transaction).

    Le schéma public est vidé entièrement avant de rejouer la copie : une table ajoutée par une mise à jour
    plus récente que la copie disparaît (migrate la recrée ensuite). pg_restore --clean ne supprime que les
    objets présents dans la copie, et échoue dès qu'une table plus récente fait référence à l'une d'elles.
    1. pg_restore convertit la copie en script SQL (fichier temporaire) : une copie tronquée ou abîmée
       échoue ici, avant que la base soit touchée ;
    2. psql rejoue « DROP SCHEMA public CASCADE ; CREATE SCHEMA public ; script » en une seule transaction,
       annulée à la première erreur. Pas de tube entre les deux : psql validerait une copie tronquée.
    """
    descripteur, nom = tempfile.mkstemp(prefix="restauration-", suffix=".sql")  # droits 0600 : contient toute la base
    os.close(descripteur)
    script = Path(nom)
    try:
        executer(["pg_restore", "--no-owner", "--no-privileges", f"--file={script}", str(fichier)], p)
        executer(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "--single-transaction", f"--dbname={p['dbname']}",
                  "-c", "SET client_min_messages = warning", "-c", "DROP SCHEMA public CASCADE", "-c", "CREATE SCHEMA public",
                  "-f", str(script)], p)
    finally:
        script.unlink(missing_ok=True)
