from django.core.management.base import BaseCommand

from bibliotheque.models import DocumentReference, StatutAnalyse, TypeDocument
from bibliotheque.tasks import analyser_document


class Command(BaseCommand):
    help = "Relance l'analyse (lecture, découpage en articles, lignes de prix) des documents de la bibliothèque."

    def add_arguments(self, parser):
        parser.add_argument("--type", choices=TypeDocument.values, help="Limiter à un type de document.")

    def handle(self, *args, **options):
        documents = DocumentReference.objects.all()
        if options["type"]:
            documents = documents.filter(type_document=options["type"])
        identifiants = list(documents.values_list("pk", flat=True))
        documents.update(statut_analyse=StatutAnalyse.EN_ATTENTE, message_analyse="")
        for identifiant in identifiants:
            analyser_document.delay(identifiant)
        self.stdout.write(self.style.SUCCESS(f"{len(identifiants)} document(s) remis en analyse."))
