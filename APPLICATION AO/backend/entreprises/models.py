"""Bibliothèque des entreprises : carnet d'adresses, spécialités (lots) et historique des consultations."""
from django.db import models

from articles.normalisation import normaliser


class Entreprise(models.Model):
    raison_sociale = models.CharField("raison sociale", max_length=255)
    siret = models.CharField("SIRET", max_length=14, blank=True, db_index=True)
    adresse = models.CharField("adresse", max_length=255, blank=True)
    code_postal = models.CharField("code postal", max_length=10, blank=True)
    ville = models.CharField("ville", max_length=120, blank=True)
    telephone = models.CharField("téléphone", max_length=30, blank=True)
    email = models.EmailField("e-mail", blank=True)
    site_web = models.CharField("site internet", max_length=255, blank=True)
    lots = models.ManyToManyField("referentiel.Lot", blank=True, related_name="entreprises", verbose_name="lots (spécialités)")
    specialites = models.CharField("savoir-faire", max_length=500, blank=True)
    qualifications = models.CharField("qualifications", max_length=500, blank=True, help_text="Qualibat, RGE, Qualifelec…")
    zone_intervention = models.CharField("zone d'intervention", max_length=255, blank=True)
    assureur_decennale = models.CharField("assureur décennale", max_length=255, blank=True)
    echeance_assurance = models.DateField("échéance de l'attestation d'assurance", null=True, blank=True)
    notes = models.TextField("notes internes", blank=True)
    actif = models.BooleanField("active", default=True)
    texte_recherche = models.TextField(blank=True, editable=False)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["raison_sociale", "id"]
        verbose_name = "entreprise"

    def __str__(self):
        return self.raison_sociale

    def save(self, *args, **kwargs):
        self.texte_recherche = normaliser(
            " ".join([self.raison_sociale, self.siret, self.ville, self.code_postal, self.specialites, self.qualifications, self.zone_intervention])
        )
        super().save(*args, **kwargs)


class Contact(models.Model):
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, related_name="contacts")
    nom = models.CharField("nom", max_length=150)
    fonction = models.CharField("fonction", max_length=150, blank=True)
    email = models.EmailField("e-mail", blank=True)
    telephone = models.CharField("téléphone", max_length=30, blank=True)
    principal = models.BooleanField("contact principal", default=False)

    class Meta:
        ordering = ["-principal", "nom", "id"]

    def __str__(self):
        return self.nom
