from decimal import Decimal

from django.conf import settings
from django.db import models

from bibliotheque.models import TypeMarche


class Police(models.TextChoices):
    ARIAL = "Arial", "Arial"
    CALIBRI = "Calibri", "Calibri"
    TIMES = "Times New Roman", "Times New Roman"


class Projet(models.Model):
    """Opération : ses informations alimentent les pages de garde des pièces écrites."""

    nom = models.CharField("nom de l'opération", max_length=255)
    numero = models.CharField("n° d'affaire", max_length=50, blank=True)
    maitre_ouvrage = models.CharField("maître d'ouvrage", max_length=255, blank=True)
    adresse_maitre_ouvrage = models.TextField("adresse du maître d'ouvrage", blank=True)
    adresse_operation = models.TextField("adresse de l'opération", blank=True)
    maitre_oeuvre = models.CharField("maîtrise d'œuvre", max_length=255, blank=True)
    type_marche = models.CharField("type de marché", max_length=10, choices=TypeMarche.choices, default=TypeMarche.PUBLIC)
    procedure = models.CharField("procédure", max_length=255, blank=True)
    phase = models.CharField("phase", max_length=20, default="DCE")
    indice = models.CharField("indice", max_length=10, default="A")
    date_document = models.DateField("date des documents", null=True, blank=True)
    taux_tva = models.DecimalField("taux de TVA (%)", max_digits=5, decimal_places=2, default=Decimal("20"))

    # Mise en forme des exports
    police = models.CharField("police", max_length=40, choices=Police.choices, default=Police.ARIAL)
    taille_police = models.PositiveSmallIntegerField("taille du texte (pt)", default=10)
    couleur_titres = models.CharField("couleur des titres", max_length=7, default="#1F3864")
    couleur_tableaux = models.CharField("fond des en-têtes de tableaux", max_length=7, default="#D9E2F3")

    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "projet"
        verbose_name_plural = "projets"
        ordering = ["-modifie_le"]

    def __str__(self):
        return self.nom


class LotProjet(models.Model):
    projet = models.ForeignKey(Projet, on_delete=models.CASCADE, related_name="lots")
    lot = models.ForeignKey("referentiel.Lot", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    code = models.CharField("code", max_length=10)
    intitule = models.CharField("intitulé", max_length=255)
    ordre = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "lot du projet"
        verbose_name_plural = "lots du projet"
        ordering = ["ordre", "code"]
        constraints = [models.UniqueConstraint(fields=["projet", "code"], name="lot_projet_code_unique")]

    def __str__(self):
        return f"{self.code} – {self.intitule}"


class GenreOption(models.TextChoices):
    PSE = "PSE", "Prestation supplémentaire éventuelle"
    VARIANTE = "VARIANTE", "Variante exigée"


class OptionLot(models.Model):
    """PSE ou variante exigée par le maître d'ouvrage, chiffrée à part dans la DPGF."""

    lot = models.ForeignKey(LotProjet, on_delete=models.CASCADE, related_name="options")
    genre = models.CharField(max_length=10, choices=GenreOption.choices, default=GenreOption.PSE)
    numero = models.PositiveSmallIntegerField(default=1)
    libelle = models.CharField("libellé", max_length=255)

    class Meta:
        verbose_name = "PSE / variante"
        verbose_name_plural = "PSE / variantes"
        ordering = ["genre", "numero"]
        constraints = [models.UniqueConstraint(fields=["lot", "genre", "numero"], name="option_lot_unique")]

    @property
    def nom_court(self) -> str:
        return f"{'PSE' if self.genre == GenreOption.PSE else 'Variante'} n°{self.numero}"

    def __str__(self):
        return f"{self.nom_court} – {self.libelle}"


class GenrePoste(models.TextChoices):
    CHAPITRE = "CHAPITRE", "Chapitre"
    ARTICLE = "ARTICLE", "Article (texte seul)"
    OUVRAGE = "OUVRAGE", "Ouvrage (chiffré)"


class Poste(models.Model):
    """Élément d'un lot : chapitre, article du CCTP, ou ouvrage repris dans la DPGF."""

    lot = models.ForeignKey(LotProjet, on_delete=models.CASCADE, related_name="postes")
    ordre = models.PositiveIntegerField(default=0)
    genre = models.CharField(max_length=10, choices=GenrePoste.choices, default=GenrePoste.OUVRAGE)
    titre = models.CharField("titre", max_length=500)
    description = models.TextField("description (HTML)", blank=True)
    unite = models.CharField("unité", max_length=20, blank=True)
    quantite = models.DecimalField("quantité", max_digits=14, decimal_places=3, null=True, blank=True)
    prix_unitaire = models.DecimalField("prix unitaire estimé HT", max_digits=14, decimal_places=2, null=True, blank=True)
    option = models.ForeignKey(OptionLot, null=True, blank=True, on_delete=models.SET_NULL, related_name="postes")
    article_source = models.ForeignKey("articles.Article", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "poste"
        verbose_name_plural = "postes"
        ordering = ["ordre", "id"]

    def __str__(self):
        return self.titre

    @property
    def montant(self) -> Decimal | None:
        if self.genre != GenrePoste.OUVRAGE or self.quantite is None or self.prix_unitaire is None:
            return None
        return (self.quantite * self.prix_unitaire).quantize(Decimal("0.01"))
