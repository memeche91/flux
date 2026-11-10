"""python manage.py sauvegarder : sauvegarde complète immédiate (à lancer dans le service worker,
où le fichier .env est monté : docker compose exec worker python manage.py sauvegarder)."""
from django.core.management.base import BaseCommand, CommandError

from sauvegardes.models import StatutSauvegarde
from sauvegardes.postgres import ErreurSauvegarde
from sauvegardes.services import destination_affichee, lancer


class Command(BaseCommand):
    help = "Sauvegarde maintenant la base (vérifiée par une restauration d’essai), la configuration et, s’ils sont sur le PC, les fichiers."

    def handle(self, *args, **options):
        self.stdout.write(f"Sauvegarde vers {destination_affichee()}…")
        try:
            sauvegarde = lancer("commande")
        except ErreurSauvegarde as exc:
            raise CommandError(f"Sauvegarde impossible : {exc}") from exc
        if sauvegarde is None:
            raise CommandError("Une sauvegarde est déjà en cours : attendez qu’elle se termine.")
        self.stdout.write(sauvegarde.message)
        if sauvegarde.statut != StatutSauvegarde.REUSSIE:
            raise CommandError("La sauvegarde a échoué.")
        if not sauvegarde.verifiee:
            self.stdout.write(self.style.WARNING("Sauvegarde faite, mais la restauration d’essai de la base n’a pas réussi."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Sauvegarde réussie : {sauvegarde.fichier}"))
