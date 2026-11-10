from django.db import models
from django.utils import timezone


class StatutSauvegarde(models.TextChoices):
    EN_COURS = "EN_COURS", "En cours"
    REUSSIE = "REUSSIE", "Réussie"
    ECHEC = "ECHEC", "Échec"


class Sauvegarde(models.Model):
    """Une sauvegarde (planifiée chaque nuit, lancée par l'administrateur ou par la commande).

    `fichier` est le chemin de la copie de la base, relatif au dossier des sauvegardes
    (base/AAAA-MM-JJ_HHMM.dump) ; `verifiee` indique que la restauration d'essai a réussi.
    """

    debut = models.DateTimeField("début", default=timezone.now)
    fin = models.DateTimeField("fin", null=True, blank=True)
    statut = models.CharField("statut", max_length=10, choices=StatutSauvegarde.choices, default=StatutSauvegarde.EN_COURS)
    fichier = models.CharField("copie de la base", max_length=255, blank=True)
    taille = models.BigIntegerField("taille (octets)", default=0)
    verifiee = models.BooleanField("vérifiée par une restauration d'essai", default=False)
    fichiers_copies = models.IntegerField("fichiers copiés", default=0)
    message = models.TextField("compte rendu", blank=True)
    declenchee_par = models.CharField("lancée par", max_length=150, blank=True)

    class Meta:
        ordering = ["-debut", "-id"]
        verbose_name = "sauvegarde"
        verbose_name_plural = "sauvegardes"
        indexes = [models.Index(fields=["statut", "debut"])]

    def __str__(self):
        return f"Sauvegarde du {timezone.localtime(self.debut):%d/%m/%Y %H:%M} ({self.get_statut_display()})"
