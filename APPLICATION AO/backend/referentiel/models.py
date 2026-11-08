from django.db import models


class Lot(models.Model):
    """Lot technique de la nomenclature du cabinet (modifiable dans l'administration)."""

    code = models.CharField("code", max_length=10, unique=True)
    intitule = models.CharField("intitulé", max_length=200)
    ordre = models.PositiveIntegerField("ordre d'affichage", default=0)
    actif = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "lot"
        verbose_name_plural = "lots"
        ordering = ["ordre", "code"]

    def __str__(self):
        return f"{self.code} – {self.intitule}"
