import uuid

from django.conf import settings
from django.db import models
from django.utils.text import get_valid_filename


class TypeDocument(models.TextChoices):
    CCAP = "CCAP", "CCAP"
    AE = "AE", "Acte d'engagement"
    RC = "RC", "Règlement de consultation"
    CCTP = "CCTP", "CCTP"
    DPGF = "DPGF", "DPGF"


# Les CCTP et DPGF sont classés par lot ; les autres pièces sont communes.
TYPES_PAR_LOT = {TypeDocument.CCTP, TypeDocument.DPGF}


class TypeMarche(models.TextChoices):
    PUBLIC = "PUBLIC", "Marché public"
    PRIVE = "PRIVE", "Marché privé"


class StatutAnalyse(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    ANALYSE = "ANALYSE", "Analysé"
    NON_PRIS_EN_CHARGE = "NON_PRIS_EN_CHARGE", "Conservé, non analysé"
    ERREUR = "ERREUR", "Erreur d'analyse"


def chemin_fichier(instance, nom_fichier):
    """bibliotheque/<TYPE>/<lot ou commun>/<identifiant>_<nom>."""
    dossier_lot = instance.lot.code if instance.lot_id else "commun"
    nom = get_valid_filename(nom_fichier)[-150:]
    return f"bibliotheque/{instance.type_document}/{dossier_lot}/{uuid.uuid4().hex[:12]}_{nom}"


class DocumentReference(models.Model):
    """Ancien document du cabinet servant de référence (style, articles, prix)."""

    type_document = models.CharField(
        "type de document", max_length=10, choices=TypeDocument.choices, db_index=True
    )
    lot = models.ForeignKey(
        "referentiel.Lot",
        verbose_name="lot",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="documents_reference",
    )
    fichier = models.FileField("fichier", upload_to=chemin_fichier, max_length=500)
    nom_original = models.CharField("nom du fichier", max_length=255)
    taille = models.PositiveBigIntegerField("taille (octets)")
    empreinte_sha256 = models.CharField("empreinte SHA-256", max_length=64, db_index=True)
    operation = models.CharField("opération d'origine", max_length=255, blank=True)
    annee = models.PositiveSmallIntegerField("année", null=True, blank=True)
    type_marche = models.CharField(
        "type de marché", max_length=10, choices=TypeMarche.choices, blank=True
    )
    statut_analyse = models.CharField(
        "statut de l'analyse",
        max_length=20,
        choices=StatutAnalyse.choices,
        default=StatutAnalyse.EN_ATTENTE,
    )
    message_analyse = models.CharField("détail de l'analyse", max_length=500, blank=True)
    texte_extrait = models.TextField("texte extrait", blank=True)
    ajoute_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ajouté par",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    ajoute_le = models.DateTimeField("ajouté le", auto_now_add=True)

    class Meta:
        verbose_name = "document de référence"
        verbose_name_plural = "documents de référence"
        ordering = ["-ajoute_le", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["type_document", "empreinte_sha256"],
                name="document_reference_unique_par_type",
            )
        ]

    def __str__(self):
        return f"{self.get_type_document_display()} – {self.nom_original}"
