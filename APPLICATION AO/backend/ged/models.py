"""GED de chantier : espace d'échange par projet, intervenants (accès par code), documents,
indices de modification (versions), visas et journal complet."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import get_valid_filename


class StatutEspace(models.TextChoices):
    OUVERT = "OUVERT", "Ouvert"
    CLOS = "CLOS", "Clos"


class EspaceChantier(models.Model):
    projet = models.OneToOneField("projets.Projet", on_delete=models.CASCADE, related_name="espace_chantier")
    statut = models.CharField(max_length=6, choices=StatutEspace.choices, default=StatutEspace.OUVERT)
    ouvert_le = models.DateTimeField(default=timezone.now)
    ouvert_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    notifications = models.BooleanField("notifications par courriel", default=True)
    emails_moe = models.TextField("courriels de la maîtrise d'œuvre (un par ligne)", blank=True)
    message_accueil = models.TextField(blank=True)
    delai_visa_jours = models.PositiveSmallIntegerField("délai de visa (jours)", default=15)

    class Meta:
        verbose_name = "espace de chantier"
        verbose_name_plural = "espaces de chantier"

    def __str__(self):
        return f"GED – {self.projet.nom}"

    def liste_emails_moe(self) -> list[str]:
        return [e.strip() for e in self.emails_moe.replace(",", "\n").replace(";", "\n").splitlines() if e.strip()]


class Profil(models.TextChoices):
    ENTREPRISE = "ENTREPRISE", "Entreprise (ses lots)"
    MOE_EXTERNE = "MOE_EXTERNE", "Maîtrise d'œuvre associée (BET, architecte)"
    LECTEUR = "LECTEUR", "Lecture seule (maître d'ouvrage, contrôleur technique, CSPS)"


class Intervenant(models.Model):
    """Personne ou société qui accède à la GED par un code (sans compte dans l'application)."""

    espace = models.ForeignKey(EspaceChantier, on_delete=models.CASCADE, related_name="intervenants")
    entreprise = models.ForeignKey("entreprises.Entreprise", null=True, blank=True, on_delete=models.SET_NULL, related_name="acces_ged")
    nom = models.CharField("nom affiché", max_length=255)
    profil = models.CharField(max_length=12, choices=Profil.choices, default=Profil.ENTREPRISE)
    lots = models.ManyToManyField("projets.LotProjet", blank=True, related_name="intervenants_ged")
    emails = models.TextField("courriels de notification (un par ligne)", blank=True)
    notifications = models.BooleanField(default=True)
    code_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True)
    code_fin = models.CharField("fin du code (affichage)", max_length=4, blank=True)
    code_genere_le = models.DateTimeField(null=True, blank=True)
    actif = models.BooleanField(default=True)
    dernier_acces = models.DateTimeField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["profil", "nom", "id"]

    def __str__(self):
        return self.nom

    def liste_emails(self) -> list[str]:
        return [e.strip() for e in self.emails.replace(",", "\n").replace(";", "\n").splitlines() if e.strip()]


class Zone(models.TextChoices):
    COMMUN = "COMMUN", "Commun à tous"
    LOT = "LOT", "Lot"
    MOE = "MOE", "Maîtrise d'œuvre (réservé)"


class Categorie(models.TextChoices):
    PLANS = "PLANS", "Plans"
    EXECUTION = "EXECUTION", "Documents d'exécution"
    FICHES = "FICHES", "Fiches techniques, avis techniques"
    NOTES = "NOTES", "Notes de calcul"
    COMPTES_RENDUS = "COMPTES_RENDUS", "Comptes rendus de chantier"
    PLANNING = "PLANNING", "Planning"
    ADMINISTRATIF = "ADMINISTRATIF", "Pièces administratives (OS, avenants)"
    DOE = "DOE", "DOE"
    PHOTOS = "PHOTOS", "Photos"
    AUTRES = "AUTRES", "Autres documents"


SIGLES_CATEGORIES = {
    Categorie.PLANS: "PLN", Categorie.EXECUTION: "EXE", Categorie.FICHES: "FT", Categorie.NOTES: "NDC",
    Categorie.COMPTES_RENDUS: "CR", Categorie.PLANNING: "PLG", Categorie.ADMINISTRATIF: "ADM", Categorie.DOE: "DOE",
    Categorie.PHOTOS: "PHO", Categorie.AUTRES: "DOC",
}
# Documents qu'une entreprise soumet au visa de la maîtrise d'œuvre.
CATEGORIES_A_VISER = {Categorie.PLANS, Categorie.EXECUTION, Categorie.FICHES, Categorie.NOTES}


class Document(models.Model):
    """Document suivi : plan, fiche, note… Il n'est jamais supprimé, seulement annulé."""

    espace = models.ForeignKey(EspaceChantier, on_delete=models.CASCADE, related_name="documents")
    zone = models.CharField(max_length=6, choices=Zone.choices)
    lot = models.ForeignKey("projets.LotProjet", null=True, blank=True, on_delete=models.CASCADE, related_name="documents_ged")
    categorie = models.CharField(max_length=16, choices=Categorie.choices, default=Categorie.PLANS)
    reference = models.CharField("référence", max_length=60)
    titre = models.CharField(max_length=255)
    auteur_intervenant = models.ForeignKey(Intervenant, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents")
    auteur_utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    auteur_nom = models.CharField(max_length=255)
    cree_le = models.DateTimeField(auto_now_add=True)
    annule = models.BooleanField(default=False)
    motif_annulation = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["zone", "lot__ordre", "lot__code", "categorie", "reference", "id"]
        constraints = [models.UniqueConstraint(fields=["espace", "reference"], name="reference_ged_unique")]

    def __str__(self):
        return f"{self.reference} – {self.titre}"


class StatutVisa(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente de visa"
    VSO = "VSO", "Visa sans observation"
    VAO = "VAO", "Visa avec observations"
    REFUSE = "REFUSE", "Refusé"
    SANS_OBJET = "SANS_OBJET", "Pour information"


def chemin_version(instance, nom_fichier):
    nom = get_valid_filename(nom_fichier)[-150:]
    document = instance.document
    return f"ged/{document.espace.projet_id}/{document.pk}/{uuid.uuid4().hex[:12]}_{nom}"


def chemin_visa(instance, nom_fichier):
    nom = get_valid_filename(nom_fichier)[-150:]
    document = instance.document
    return f"ged/{document.espace.projet_id}/{document.pk}/visa_{uuid.uuid4().hex[:12]}_{nom}"


class Version(models.Model):
    """Indice d'un document : fichier déposé, objet de la modification, visa."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    indice = models.CharField(max_length=3)
    fichier = models.FileField(upload_to=chemin_version, max_length=500)
    nom_original = models.CharField(max_length=255)
    taille = models.PositiveBigIntegerField()
    empreinte = models.CharField("SHA-256", max_length=64)
    objet = models.CharField("objet de la modification", max_length=500, blank=True)
    deposee_par_intervenant = models.ForeignKey(Intervenant, null=True, blank=True, on_delete=models.SET_NULL, related_name="versions")
    deposee_par_utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    deposee_par_nom = models.CharField(max_length=255)
    deposee_le = models.DateTimeField(default=timezone.now)
    visa = models.CharField(max_length=10, choices=StatutVisa.choices, default=StatutVisa.SANS_OBJET)
    visa_commentaire = models.TextField(blank=True)
    visa_fichier = models.FileField(upload_to=chemin_visa, max_length=500, blank=True)
    visa_nom_original = models.CharField(max_length=255, blank=True)
    vise_par_nom = models.CharField(max_length=255, blank=True)
    vise_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["document", "-deposee_le", "-id"]
        constraints = [models.UniqueConstraint(fields=["document", "indice"], name="indice_ged_unique")]


class TypeEvenement(models.TextChoices):
    DEPOT = "DEPOT", "Nouveau document"
    INDICE = "INDICE", "Nouvel indice"
    VISA = "VISA", "Visa"
    ANNULATION = "ANNULATION", "Document annulé"
    MODIFICATION = "MODIFICATION", "Document modifié"
    TELECHARGEMENT = "TELECHARGEMENT", "Téléchargement"
    CONNEXION = "CONNEXION", "Connexion"
    ACCES = "ACCES", "Accès modifié"
    ESPACE = "ESPACE", "Espace"


class Evenement(models.Model):
    """Journal complet de l'espace (conservé dans l'archive du projet)."""

    espace = models.ForeignKey(EspaceChantier, on_delete=models.CASCADE, related_name="evenements")
    type = models.CharField(max_length=14, choices=TypeEvenement.choices)
    date = models.DateTimeField(default=timezone.now)
    document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.SET_NULL, related_name="evenements")
    version = models.ForeignKey(Version, null=True, blank=True, on_delete=models.SET_NULL, related_name="evenements")
    intervenant = models.ForeignKey(Intervenant, null=True, blank=True, on_delete=models.SET_NULL, related_name="evenements")
    acteur = models.CharField(max_length=255)
    description = models.CharField(max_length=1000)
    a_notifier = models.BooleanField(default=False)
    notifie_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["espace", "a_notifier"])]


class StatutArchive(models.TextChoices):
    EN_COURS = "EN_COURS", "En préparation"
    PRETE = "PRETE", "Prête"
    ERREUR = "ERREUR", "Erreur"


class ProjetArchive(models.Model):
    """Archive complète d'un projet (.zip dans le dossier d'archives du cabinet).

    Elle reste listée après la suppression du projet de l'application.
    """

    projet = models.ForeignKey("projets.Projet", null=True, blank=True, on_delete=models.SET_NULL, related_name="archives")
    nom_projet = models.CharField(max_length=255)
    numero_projet = models.CharField(max_length=50, blank=True)
    statut = models.CharField(max_length=8, choices=StatutArchive.choices, default=StatutArchive.EN_COURS)
    message = models.CharField(max_length=500, blank=True)
    nom_fichier = models.CharField(max_length=255, blank=True)
    taille = models.PositiveBigIntegerField(default=0)
    empreinte = models.CharField("SHA-256", max_length=64, blank=True)
    nb_fichiers = models.PositiveIntegerField(default=0)
    demandee_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)
    terminee_le = models.DateTimeField(null=True, blank=True)
    telechargee_le = models.DateTimeField(null=True, blank=True)
    projet_supprime_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-cree_le", "-id"]

    def __str__(self):
        return f"Archive {self.nom_projet} ({self.cree_le:%d/%m/%Y})"
