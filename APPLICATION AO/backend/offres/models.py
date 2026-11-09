"""Offres reçues des entreprises, lignes de prix lues, paramètres d'analyse et notation par lot."""
import uuid

from django.db import models
from django.utils import timezone
from django.utils.text import get_valid_filename


def chemin_offre(instance, nom_fichier):
    nom = get_valid_filename(nom_fichier)[-150:]
    return f"offres/{instance.projet_id}/{instance.lot_id}/{uuid.uuid4().hex[:12]}_{nom}"


class StatutLecture(models.TextChoices):
    EN_COURS = "EN_COURS", "Lecture en cours"
    LUE = "LUE", "Lue"
    A_VERIFIER = "A_VERIFIER", "À vérifier"
    NON_LUE = "NON_LUE", "Montant à saisir"
    MANUELLE = "MANUELLE", "Saisie manuelle"


class Offre(models.Model):
    projet = models.ForeignKey("projets.Projet", on_delete=models.CASCADE, related_name="offres")
    lot = models.ForeignKey("projets.LotProjet", on_delete=models.CASCADE, related_name="offres")
    entreprise = models.ForeignKey("entreprises.Entreprise", on_delete=models.PROTECT, related_name="offres")
    variante = models.BooleanField("variante à l'initiative de l'entreprise", default=False)
    libelle_variante = models.CharField(max_length=255, blank=True)
    recue_le = models.DateField("reçue le", default=timezone.localdate)
    fichier = models.FileField(upload_to=chemin_offre, max_length=500, blank=True)
    nom_original = models.CharField(max_length=255, blank=True)
    statut_lecture = models.CharField(max_length=12, choices=StatutLecture.choices, default=StatutLecture.MANUELLE)
    message_lecture = models.CharField(max_length=500, blank=True)
    montant_base = models.DecimalField("montant de la solution de base HT", max_digits=14, decimal_places=2, null=True, blank=True)
    montant_base_calcule = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    montant_base_declare = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    montants_options = models.JSONField("montants des PSE et variantes exigées", default=dict, blank=True)
    delai_propose = models.CharField("délai proposé", max_length=255, blank=True)
    commentaire = models.TextField(blank=True)
    ecartee = models.BooleanField("offre écartée", default=False)
    motif_ecart = models.CharField(max_length=500, blank=True)
    notes = models.JSONField("notes par critère", default=dict, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["lot__ordre", "lot__code", "entreprise__raison_sociale", "variante", "id"]

    @property
    def nom(self) -> str:
        if self.variante:
            return f"{self.entreprise.raison_sociale} – variante{f' ({self.libelle_variante})' if self.libelle_variante else ''}"
        return self.entreprise.raison_sociale


class LigneOffre(models.Model):
    offre = models.ForeignKey(Offre, on_delete=models.CASCADE, related_name="lignes")
    poste = models.ForeignKey("projets.Poste", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    option = models.ForeignKey("projets.OptionLot", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    ordre = models.PositiveIntegerField()
    numero = models.CharField(max_length=50, blank=True)
    designation = models.TextField()
    unite = models.CharField(max_length=20, blank=True)
    quantite = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    prix_unitaire = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    montant = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    correspondance = models.CharField(max_length=12, blank=True)  # NUMERO, DESIGNATION ou vide

    class Meta:
        ordering = ["ordre"]


class MethodePrix(models.TextChoices):
    PROPORTIONNELLE = "PROPORTIONNELLE", "Proportionnelle : note max × prix le plus bas / prix de l'offre"
    LINEAIRE = "LINEAIRE", "Linéaire : note max × (1 − écart relatif au prix le plus bas)"


class AnalyseLot(models.Model):
    lot = models.OneToOneField("projets.LotProjet", on_delete=models.CASCADE, related_name="analyse")
    methode_prix = models.CharField(max_length=16, choices=MethodePrix.choices, default=MethodePrix.PROPORTIONNELLE)
    bareme = models.PositiveSmallIntegerField("notes sur", default=10)
    options_retenues = models.ManyToManyField("projets.OptionLot", blank=True, related_name="+")
    seuil_anormal = models.PositiveSmallIntegerField("seuil d'offre anormalement basse (%)", default=20)
    attributaire = models.ForeignKey(Offre, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    observations = models.TextField(blank=True)
    validee_le = models.DateTimeField(null=True, blank=True)
