"""DCE : documents joints, dossiers .zip générés, entreprises consultées et envois."""
import uuid

from django.conf import settings
from django.db import models
from django.utils.text import get_valid_filename


class CategoriePieceJointe(models.TextChoices):
    PLANS = "PLANS", "Plans"
    ETUDES = "ETUDES", "Études et rapports"
    DIAGNOSTICS = "DIAGNOSTICS", "Diagnostics"
    SPS = "SPS", "Sécurité et santé (PGC)"
    AUTRES = "AUTRES", "Autres documents"


def chemin_piece_jointe(instance, nom_fichier):
    nom = get_valid_filename(nom_fichier)[-150:]
    return f"dce/{instance.projet_id}/documents/{uuid.uuid4().hex[:12]}_{nom}"


def chemin_dossier(instance, nom_fichier):
    nom = get_valid_filename(nom_fichier)[-150:]
    return f"dce/{instance.projet_id}/dossiers/{uuid.uuid4().hex[:12]}_{nom}"


class PieceJointe(models.Model):
    """Document ajouté au DCE en plus des pièces écrites : plans, études, diagnostics, PGC…"""

    projet = models.ForeignKey("projets.Projet", on_delete=models.CASCADE, related_name="pieces_jointes")
    categorie = models.CharField(max_length=12, choices=CategoriePieceJointe.choices, default=CategoriePieceJointe.PLANS)
    lot = models.ForeignKey("projets.LotProjet", null=True, blank=True, on_delete=models.CASCADE, related_name="pieces_jointes")
    titre = models.CharField("titre", max_length=255)
    fichier = models.FileField(upload_to=chemin_piece_jointe, max_length=500)
    nom_original = models.CharField(max_length=255)
    taille = models.PositiveBigIntegerField()
    ajoute_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["categorie", "lot__code", "titre", "id"]


class StatutDossier(models.TextChoices):
    EN_COURS = "EN_COURS", "En préparation"
    PRET = "PRET", "Prêt"
    ERREUR = "ERREUR", "Erreur"


class DossierDCE(models.Model):
    """Dossier .zip produit : DCE complet, ou dossier personnalisé pour une entreprise (ses lots)."""

    projet = models.ForeignKey("projets.Projet", on_delete=models.CASCADE, related_name="dossiers_dce")
    indice = models.CharField("indice", max_length=10)
    entreprise = models.ForeignKey("entreprises.Entreprise", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    lots = models.ManyToManyField("projets.LotProjet", blank=True, related_name="+")
    avec_word = models.BooleanField("versions Word des pièces écrites", default=False)
    statut = models.CharField(max_length=10, choices=StatutDossier.choices, default=StatutDossier.EN_COURS)
    message = models.CharField(max_length=500, blank=True)
    fichier = models.FileField(upload_to=chemin_dossier, max_length=500, blank=True)
    nom = models.CharField("nom du fichier", max_length=255, blank=True)
    taille = models.PositiveBigIntegerField(default=0)
    contenu = models.JSONField("arborescence", default=list, blank=True)
    alertes = models.JSONField(default=list, blank=True)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-cree_le", "-id"]


class StatutConsultation(models.TextChoices):
    A_CONSULTER = "A_CONSULTER", "À consulter"
    CONSULTEE = "CONSULTEE", "Consultée"
    REPONDU = "REPONDU", "A remis une offre"
    EXCUSEE = "EXCUSEE", "S'est excusée"
    RETENUE = "RETENUE", "Retenue"
    NON_RETENUE = "NON_RETENUE", "Non retenue"


class ConsultationEntreprise(models.Model):
    """Entreprise consultée pour un lot d'un projet : alimente l'historique de l'annuaire."""

    projet = models.ForeignKey("projets.Projet", on_delete=models.CASCADE, related_name="consultations_entreprises")
    lot = models.ForeignKey("projets.LotProjet", on_delete=models.CASCADE, related_name="consultations_entreprises")
    entreprise = models.ForeignKey("entreprises.Entreprise", on_delete=models.CASCADE, related_name="consultations")
    statut = models.CharField(max_length=12, choices=StatutConsultation.choices, default=StatutConsultation.A_CONSULTER)
    consultee_le = models.DateField(null=True, blank=True)
    commentaire = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["lot__ordre", "lot__code", "entreprise__raison_sociale"]
        constraints = [models.UniqueConstraint(fields=["lot", "entreprise"], name="consultation_lot_entreprise_unique")]


class TypeEnvoi(models.TextChoices):
    MOA = "MOA", "Transmission au maître d'ouvrage"
    ENTREPRISE = "ENTREPRISE", "Envoi à une entreprise"


class ModeEnvoi(models.TextChoices):
    EMAIL = "EMAIL", "Par e-mail depuis l'application"
    MANUEL = "MANUEL", "Par vos soins (messagerie, transfert de fichiers)"


class StatutEnvoi(models.TextChoices):
    PREPARATION = "PREPARATION", "En préparation"
    A_ENVOYER = "A_ENVOYER", "Prêt : à envoyer par vos soins"
    ENVOYE = "ENVOYE", "Envoyé"
    ERREUR = "ERREUR", "Échec"


class Envoi(models.Model):
    projet = models.ForeignKey("projets.Projet", on_delete=models.CASCADE, related_name="envois_dce")
    type_envoi = models.CharField(max_length=10, choices=TypeEnvoi.choices)
    entreprise = models.ForeignKey("entreprises.Entreprise", null=True, blank=True, on_delete=models.SET_NULL, related_name="envois")
    dossier = models.ForeignKey(DossierDCE, null=True, blank=True, on_delete=models.SET_NULL, related_name="envois")
    lots = models.ManyToManyField("projets.LotProjet", blank=True, related_name="+")
    destinataires = models.CharField(max_length=1000)
    objet = models.CharField(max_length=255)
    message = models.TextField()
    mode = models.CharField(max_length=10, choices=ModeEnvoi.choices)
    piece_jointe = models.BooleanField("dossier joint au courriel", default=False)
    statut = models.CharField(max_length=12, choices=StatutEnvoi.choices, default=StatutEnvoi.PREPARATION)
    erreur = models.CharField(max_length=500, blank=True)
    envoye_le = models.DateTimeField(null=True, blank=True)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-cree_le", "-id"]
