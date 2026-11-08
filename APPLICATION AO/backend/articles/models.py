from django.db import models


class Categorie(models.TextChoices):
    GENERALITES = "GENERALITES", "Généralités"
    OUVRAGE = "OUVRAGE", "Ouvrage"
    CLAUSE = "CLAUSE", "Clause administrative"


class Article(models.Model):
    """Article (ou clause) extrait d'un document de la bibliothèque."""

    document = models.ForeignKey(
        "bibliotheque.DocumentReference", on_delete=models.CASCADE, related_name="articles"
    )
    lot = models.ForeignKey(
        "referentiel.Lot", null=True, blank=True, on_delete=models.SET_NULL, related_name="articles"
    )
    ordre = models.PositiveIntegerField("ordre dans le document")
    numero = models.CharField("numéro", max_length=50, blank=True)
    titre = models.CharField("titre", max_length=500)
    chemin = models.CharField("rubrique", max_length=1000, blank=True)
    niveau = models.PositiveSmallIntegerField("niveau de titre", default=1)
    contenu = models.TextField("contenu")
    categorie = models.CharField("catégorie", max_length=20, choices=Categorie.choices, db_index=True)
    # Références stockées sous la forme « |DTU 36.5|NF EN 14351-1| » (filtrage simple).
    references_normatives = models.TextField("références normatives", blank=True)
    texte_recherche = models.TextField(blank=True, editable=False)

    class Meta:
        verbose_name = "article"
        verbose_name_plural = "articles"
        ordering = ["document_id", "ordre"]

    def __str__(self):
        return " ".join(p for p in (self.numero, self.titre) if p)

    @property
    def liste_references(self) -> list[str]:
        return [r for r in self.references_normatives.strip("|").split("|") if r]


class LignePrix(models.Model):
    """Ligne d'une DPGF : désignation, unité, quantité et prix unitaire."""

    document = models.ForeignKey(
        "bibliotheque.DocumentReference", on_delete=models.CASCADE, related_name="lignes_prix"
    )
    lot = models.ForeignKey(
        "referentiel.Lot", null=True, blank=True, on_delete=models.SET_NULL, related_name="lignes_prix"
    )
    ordre = models.PositiveIntegerField("ordre dans le document")
    numero = models.CharField("numéro", max_length=50, blank=True)
    chapitre = models.CharField("chapitre", max_length=500, blank=True)
    designation = models.TextField("désignation")
    unite = models.CharField("unité", max_length=20, blank=True)
    unite_normalisee = models.CharField(max_length=20, blank=True, db_index=True, editable=False)
    quantite = models.DecimalField("quantité", max_digits=14, decimal_places=3, null=True, blank=True)
    prix_unitaire = models.DecimalField("prix unitaire HT", max_digits=14, decimal_places=2, null=True, blank=True)
    montant = models.DecimalField("montant HT", max_digits=16, decimal_places=2, null=True, blank=True)
    designation_normalisee = models.TextField(blank=True, editable=False)

    class Meta:
        verbose_name = "ligne de prix"
        verbose_name_plural = "lignes de prix"
        ordering = ["document_id", "ordre"]

    def __str__(self):
        return self.designation[:80]
