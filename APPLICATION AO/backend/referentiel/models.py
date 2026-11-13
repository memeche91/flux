from django.db import models


class Lot(models.Model):
    """Lot technique de la nomenclature du cabinet (modifiable dans l'administration)."""

    code = models.CharField("code", max_length=10, unique=True)
    intitule = models.CharField("intitulé", max_length=200)
    ordre = models.PositiveIntegerField("ordre d'affichage", default=0)
    # actif : lot utilisable partout (bibliothèque, articles, prix, entreprises). propose : coché dans la liste de
    # création des projets (écran « Lots proposés ») ; le retirer de cette liste ne touche pas au reste.
    actif = models.BooleanField("actif", default=True)
    propose = models.BooleanField("proposé à la création des projets", default=True)

    class Meta:
        verbose_name = "lot"
        verbose_name_plural = "lots"
        ordering = ["ordre", "code"]

    def __str__(self):
        return f"{self.code} – {self.intitule}"
