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


# --- Pièces administratives (étape 1.3) ------------------------------------------


def criteres_par_defaut() -> list[dict]:
    """Critères proposés : depuis le 21 août 2026, un critère environnemental est obligatoire."""
    return [
        {"libelle": "Valeur technique", "ponderation": 50},
        {"libelle": "Prix", "ponderation": 40},
        {"libelle": "Performance en matière de protection de l'environnement", "ponderation": 10},
    ]


class Visite(models.TextChoices):
    SANS_OBJET = "SANS_OBJET", "Pas de visite"
    FACULTATIVE = "FACULTATIVE", "Visite facultative"
    OBLIGATOIRE = "OBLIGATOIRE", "Visite obligatoire"


class FormePrix(models.TextChoices):
    FERME_ACTUALISABLE = "FERME_ACTUALISABLE", "fermes et actualisables"
    REVISABLE = "REVISABLE", "révisables"


class Consultation(models.Model):
    """Paramètres de la consultation : ils alimentent le RC, le CCAP et les actes d'engagement."""

    projet = models.OneToOneField(Projet, on_delete=models.CASCADE, related_name="consultation")
    date_limite_offres = models.DateTimeField("date limite de remise des offres", null=True, blank=True)
    duree_validite_offres = models.PositiveSmallIntegerField("validité des offres (jours)", default=120)
    delai_execution = models.CharField("délai d'exécution", max_length=255, blank=True)
    date_debut_travaux = models.CharField("démarrage prévisionnel", max_length=100, blank=True)
    visite = models.CharField("visite du site", max_length=12, choices=Visite.choices, default=Visite.FACULTATIVE)
    modalites_visite = models.CharField("modalités de la visite", max_length=255, blank=True)
    variantes_autorisees = models.BooleanField("variantes autorisées", default=False)
    forme_prix = models.CharField("forme des prix", max_length=20, choices=FormePrix.choices, default=FormePrix.FERME_ACTUALISABLE)
    index_reference = models.CharField("index de référence", max_length=50, default="BT01")
    taux_retenue_garantie = models.DecimalField("retenue de garantie (%)", max_digits=5, decimal_places=2, default=Decimal("5"))
    taux_avance = models.DecimalField("avance (%)", max_digits=5, decimal_places=2, default=Decimal("5"))
    penalites_retard = models.CharField(
        "pénalités de retard", max_length=255, default="1/3000e du montant hors taxes du marché par jour calendaire de retard"
    )
    profil_acheteur = models.CharField("profil d'acheteur", max_length=255, blank=True)
    contact = models.CharField("contact pour les questions", max_length=255, blank=True)
    criteres = models.JSONField("critères de jugement", default=criteres_par_defaut)

    class Meta:
        verbose_name = "consultation"
        verbose_name_plural = "consultations"

    def __str__(self):
        return f"Consultation – {self.projet}"


class TypePiece(models.TextChoices):
    CCAP = "CCAP", "Cahier des Clauses Administratives Particulières"
    RC = "RC", "Règlement de la Consultation"
    AE = "AE", "Acte d'Engagement"


class GenreClause(models.TextChoices):
    CHAPITRE = "CHAPITRE", "Article (titre de premier niveau)"
    ARTICLE = "ARTICLE", "Sous-article"


class PieceEcrite(models.Model):
    """CCAP ou RC (un par projet) ; acte d'engagement (un par lot)."""

    projet = models.ForeignKey(Projet, on_delete=models.CASCADE, related_name="pieces")
    type_piece = models.CharField("type de pièce", max_length=4, choices=TypePiece.choices)
    lot = models.ForeignKey(LotProjet, null=True, blank=True, on_delete=models.CASCADE, related_name="pieces")
    titre = models.CharField("titre", max_length=255)
    origine = models.CharField("créée à partir de", max_length=255, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "pièce écrite"
        verbose_name_plural = "pièces écrites"
        ordering = ["type_piece", "lot__ordre", "lot__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["projet", "type_piece"], condition=models.Q(lot__isnull=True), name="piece_unique_par_projet"
            ),
            models.UniqueConstraint(
                fields=["projet", "type_piece", "lot"], condition=models.Q(lot__isnull=False), name="piece_unique_par_lot"
            ),
        ]

    def __str__(self):
        suffixe = f" – lot {self.lot.code}" if self.lot_id else ""
        return f"{self.type_piece}{suffixe} – {self.projet}"


class Clause(models.Model):
    piece = models.ForeignKey(PieceEcrite, on_delete=models.CASCADE, related_name="clauses")
    ordre = models.PositiveIntegerField(default=0)
    genre = models.CharField(max_length=10, choices=GenreClause.choices, default=GenreClause.ARTICLE)
    titre = models.CharField("titre", max_length=500)
    contenu = models.TextField("contenu (HTML)", blank=True)
    article_source = models.ForeignKey("articles.Article", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "clause"
        verbose_name_plural = "clauses"
        ordering = ["ordre", "id"]

    def __str__(self):
        return self.titre


class ModelePiece(models.Model):
    """Modèle du cabinet, enregistré à partir d'une pièce rédigée (réutilisable sur d'autres projets)."""

    nom = models.CharField("nom", max_length=255)
    type_piece = models.CharField("type de pièce", max_length=4, choices=TypePiece.choices)
    marche = models.CharField("marché", max_length=10, choices=TypeMarche.choices, default=TypeMarche.PUBLIC)
    clauses = models.JSONField("clauses", default=list)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "modèle du cabinet"
        verbose_name_plural = "modèles du cabinet"
        ordering = ["type_piece", "nom"]

    def __str__(self):
        return self.nom
