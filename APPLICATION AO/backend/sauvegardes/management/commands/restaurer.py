"""python manage.py restaurer <copie.dump> --confirmer : remplace la base de l'application par une copie.

D'ordinaire lancée par restaurer.ps1 ; sinon, dans le dossier de l'application, application arrêtée et base
démarrée (docker compose up -d base redis) :
    docker compose run --rm --no-deps -T worker python manage.py restaurer 2026-11-09_0230.dump --confirmer
La base actuelle est d'abord copiée (base/avant-restauration_….dump), puis la copie est restaurée en une
seule transaction (schéma public vidé puis copie rejouée) : en cas d'erreur, la base reste telle qu'elle était.
Enfin, migrate met à jour la structure d'une copie faite par une version plus ancienne.
"""
import os
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.models import F
from django.utils import timezone

from sauvegardes import postgres
from sauvegardes.miroir import SUFFIXE_PARTIEL, miroir
from sauvegardes.models import Sauvegarde, StatutSauvegarde
from sauvegardes.postgres import ErreurSauvegarde
from sauvegardes.services import cle_secrete, destination_affichee, dossier, verrou


def trouver_copie(chemin: str) -> Path:
    """Accepte un nom (2026-11-09_0230.dump), un chemin dans le dossier des sauvegardes ou un chemin complet."""
    demande = Path(chemin.replace("\\", "/"))
    candidats = [demande] if demande.is_absolute() else [Path.cwd() / demande, dossier() / demande, dossier() / "base" / demande.name]
    for candidat in candidats:
        if candidat.is_file():
            return candidat
    raise CommandError(f"Copie « {chemin} » introuvable (cherchée dans {dossier() / 'base'}).")


def cle_sauvegardee() -> str | None:
    """DJANGO_SECRET_KEY de la copie du .env, pour prévenir si elle diffère de celle de l'application."""
    try:
        return cle_secrete((dossier() / "configuration" / ".env").read_bytes())
    except OSError:
        return None


class Command(BaseCommand):
    help = "Remplace la base de l’application par une copie sauvegardée (la base actuelle est d’abord copiée)."

    def add_arguments(self, parser):
        parser.add_argument("chemin", help="Copie à restaurer : nom (AAAA-MM-JJ_HHMM.dump) ou chemin.")
        parser.add_argument("--confirmer", action="store_true", help="Confirme le remplacement de la base actuelle.")
        parser.add_argument("--sans-copie", action="store_true", help="Ne copie pas la base actuelle avant de la remplacer.")
        parser.add_argument("--avec-fichiers", action="store_true",
                            help="Recopie aussi les fichiers et archives sauvegardés dans l’application (sans rien effacer).")

    def handle(self, *args, chemin, confirmer, sans_copie, avec_fichiers, **options):
        copie = trouver_copie(chemin)
        if not confirmer:
            self.stdout.write(self.style.WARNING(
                f"La base actuelle de l’application sera REMPLACÉE par la copie {copie.name} : tout ce qui a été saisi "
                "depuis sera perdu (une copie de la base actuelle est faite avant, sauf avec --sans-copie)."))
            raise CommandError("Relancez la commande avec --confirmer pour restaurer.")
        avant = None
        try:
            p = postgres.parametres()
            with verrou() as obtenu:
                if not obtenu:
                    raise CommandError("Une sauvegarde est en cours : attendez qu’elle se termine, puis relancez.")
                if not sans_copie:
                    avant = self._copier_base_actuelle(p)
                connections.close_all()
                self.stdout.write(f"Restauration de {copie.name}…")
                postgres.restaurer(copie, p)
        except ErreurSauvegarde as exc:
            raise CommandError(f"Restauration impossible, la base n’a pas été modifiée : {exc}") from exc
        try:
            call_command("migrate", interactive=False, verbosity=0)  # copie faite par une version plus ancienne
        except Exception as exc:  # noqa: BLE001 - la base est déjà remplacée : l'administrateur doit le savoir
            conseil = f", par exemple {avant.name} (la base d’avant la restauration)" if avant else ""
            raise CommandError(
                f"Base restaurée depuis {copie.name}, mais sa mise à jour de structure (migrate) a échoué "
                f"({exc.__class__.__name__} : {exc}). L’application ne démarrera pas avec cette base : "
                f"restaurez une autre copie{conseil}.", returncode=2) from exc
        self._noter_sauvegarde_restauree(copie)
        if avec_fichiers:
            self._recopier_fichiers()
        cle = cle_sauvegardee()
        if cle and cle != settings.SECRET_KEY:
            self.stdout.write(self.style.WARNING(
                "La clé DJANGO_SECRET_KEY de l’application diffère de celle sauvegardée : les codes d’accès des entreprises "
                f"à la GED ne fonctionneront pas. Copiez {destination_affichee()}\\configuration\\.env à la place du fichier "
                ".env de l’application, puis relancez installer.ps1."))
        self.stdout.write(self.style.SUCCESS(
            f"Base restaurée depuis {copie.name}. Redémarrez l’application (docker compose restart) avant de reprendre le travail."))

    def _copier_base_actuelle(self, p: dict) -> Path:
        dossier_base = dossier() / "base"
        dossier_base.mkdir(parents=True, exist_ok=True)
        cible = dossier_base / f"avant-restauration_{timezone.localtime():%Y-%m-%d_%H%M%S}.dump"
        partiel = cible.with_name(cible.name + SUFFIXE_PARTIEL)
        self.stdout.write(f"Copie de la base actuelle dans {cible.name}…")
        try:
            postgres.exporter(partiel, p)
            os.replace(partiel, cible)
        except BaseException:
            partiel.unlink(missing_ok=True)
            raise
        return cible

    def _noter_sauvegarde_restauree(self, copie: Path) -> None:
        """La copie contient la sauvegarde qui l'a produite, encore « en cours » à cet instant : on la clôt."""
        try:
            relatif = copie.resolve().relative_to(dossier().resolve()).as_posix()
        except ValueError:
            relatif = copie.name
        Sauvegarde.objects.filter(statut=StatutSauvegarde.EN_COURS).update(
            statut=StatutSauvegarde.REUSSIE, verifiee=True, fin=F("debut"), fichier=relatif[:255], taille=copie.stat().st_size,
            message=f"Copie de la base restaurée le {timezone.localtime():%d/%m/%Y à %H:%M} ; "
                    "le compte rendu de cette sauvegarde n’est pas dans la copie.")

    def _recopier_fichiers(self) -> None:
        maintenant = timezone.now()
        for nom, cible in (("fichiers", Path(settings.MEDIA_ROOT)), ("archives", Path(settings.DOSSIER_ARCHIVES))):
            source = dossier() / nom
            if not source.is_dir():
                self.stdout.write(f"{nom.capitalize()} : rien à recopier ({source} absent).")
                continue
            bilan = miroir(source, cible, maintenant, supprimer=False)
            self.stdout.write(f"{nom.capitalize()} : {bilan.copies} fichier(s) recopié(s).")
            for erreur in bilan.erreurs[:10]:
                self.stdout.write(self.style.WARNING(f"  non recopié : {erreur}"))
