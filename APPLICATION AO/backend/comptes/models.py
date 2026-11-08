from django.contrib.auth.models import AbstractUser
from django.db import models


class Utilisateur(AbstractUser):
    """Compte utilisateur.

    - Administrateur : accès complet, y compris l'assistant IA local.
    - Maîtrise d'œuvre : rédaction, DCE, analyse des offres, GED.
    - Entreprise : accès futur à la GED de chantier uniquement (étape 4).
    """

    class Role(models.TextChoices):
        ADMINISTRATEUR = "ADMIN", "Administrateur"
        MOE = "MOE", "Maîtrise d'œuvre"
        ENTREPRISE = "ENTREPRISE", "Entreprise"

    role = models.CharField("rôle", max_length=20, choices=Role.choices, default=Role.MOE)

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"

    @property
    def est_administrateur(self) -> bool:
        return self.is_superuser or self.role == self.Role.ADMINISTRATEUR

    @property
    def acces_bureau_etudes(self) -> bool:
        """Accès aux outils internes du cabinet (tout sauf l'espace entreprises)."""
        return self.is_active and (self.est_administrateur or self.role == self.Role.MOE)
