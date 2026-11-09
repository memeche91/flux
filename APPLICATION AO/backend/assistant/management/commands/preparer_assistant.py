"""Télécharge les modèles de l'assistant (une fois), puis indexe la bibliothèque.

    python manage.py preparer_assistant
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from assistant import ollama, voix
from assistant.tasks import indexer_assistant


class Command(BaseCommand):
    help = "Télécharge les modèles d'IA de l'assistant et indexe la bibliothèque."

    def add_arguments(self, parser):
        parser.add_argument("--sans-voix", action="store_true", help="Ne pas télécharger les modèles de voix.")
        parser.add_argument("--sans-index", action="store_true", help="Ne pas lancer l'indexation.")
        parser.add_argument("--attendre", action="store_true", help="Attendre la fin de l'indexation (sinon : en arrière-plan).")

    def handle(self, *args, **options):
        if ollama.version() is None:
            raise CommandError(f"Le moteur d'IA (Ollama) ne répond pas à l'adresse {settings.OLLAMA_URL}.")
        installes = ollama.modeles_installes()
        for nom in [settings.IA_MODELE, settings.IA_MODELE_EMBEDDING]:
            if ollama.est_installe(nom, installes):
                self.stdout.write(f"Modèle {nom} : déjà installé.")
                continue
            self.stdout.write(f"Téléchargement du modèle {nom}…")
            dernier = -1
            for etape in ollama.telecharger(nom):
                total, fait = etape.get("total"), etape.get("completed")
                if total and fait is not None:
                    pourcentage = int(fait * 100 / total)
                    if pourcentage // 10 != dernier // 10:
                        self.stdout.write(f"  {pourcentage} % ({total / 1e9:.1f} Go)")
                        dernier = pourcentage
            self.stdout.write(self.style.SUCCESS(f"Modèle {nom} installé."))

        if not options["sans_voix"]:
            self.stdout.write(f"Modèle de transcription vocale {settings.IA_WHISPER}…")
            voix.preparer_transcription()
            self.stdout.write(f"Voix de synthèse {settings.IA_VOIX}…")
            voix.preparer_synthese()
            self.stdout.write(self.style.SUCCESS("Voix installée."))

        if options["sans_index"]:
            return
        if options["attendre"]:
            self.stdout.write("Indexation de la bibliothèque (peut durer plusieurs minutes)…")
            indexer_assistant.apply()
            self.stdout.write(self.style.SUCCESS("L'assistant est prêt."))
        else:
            indexer_assistant.delay()
            self.stdout.write(self.style.SUCCESS(
                "L'assistant est prêt. Il lit vos documents en arrière-plan (suivi sur la page Assistant)."
            ))
