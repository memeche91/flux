"""GED de chantier : espace d'échange par projet, intervenants (accès par code), documents,
indices de modification (versions), visas, avis, accusés de lecture et journal complet."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import get_valid_filename

from .categories import CHOIX as CHOIX_CATEGORIES


class StatutEspace(models.TextChoices):
    OUVERT = "OUVERT", "Chantier en cours"
    RECEPTION = "RECEPTION", "Réceptionné (DOE, réserves)"
    CLOS = "CLOS", "Clos"


class EspaceChantier(models.Model):
    projet = models.OneToOneField("projets.Projet", on_delete=models.CASCADE, related_name="espace_chantier")
    statut = models.CharField(max_length=10, choices=StatutEspace.choices, default=StatutEspace.OUVERT)
    ouvert_le = models.DateTimeField(default=timezone.now)
    ouvert_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    notifications = models.BooleanField("notifications par courriel", default=True)
    emails_moe = models.TextField("courriels de la maîtrise d'œuvre (un par ligne)", blank=True)
    message_accueil = models.TextField(blank=True)
    delai_visa_jours = models.PositiveSmallIntegerField("délai de visa (jours calendaires)", default=15)
    lecture_inter_lots = models.BooleanField("les entreprises lisent les documents techniques des autres lots", default=True)
    date_reception = models.DateField("date de réception des travaux", null=True, blank=True)

    class Meta:
        verbose_name = "espace de chantier"
        verbose_name_plural = "espaces de chantier"

    def __str__(self):
        return f"GED – {self.projet.nom}"

    @property
    def actif(self) -> bool:
        return self.statut in (StatutEspace.OUVERT, StatutEspace.RECEPTION)

    def liste_emails_moe(self) -> list[str]:
        return [e.strip() for e in self.emails_moe.replace(",", "\n").replace(";", "\n").splitlines() if e.strip()]


class Profil(models.TextChoices):
    ENTREPRISE = "ENTREPRISE", "Entreprise (ses lots)"
    MOE_EXTERNE = "MOE_EXTERNE", "Maîtrise d'œuvre associée (BET, architecte)"
    MAITRE_OUVRAGE = "MAITRE_OUVRAGE", "Maître d'ouvrage (lecture)"
    CONTROLEUR_TECHNIQUE = "CT", "Contrôleur technique"
    CSPS = "CSPS", "Coordonnateur SPS"
    OPC = "OPC", "OPC (ordonnancement, pilotage)"


class Frequence(models.TextChoices):
    IMMEDIATE = "IMMEDIATE", "À chaque nouveauté"
    QUOTIDIENNE = "QUOTIDIENNE", "Récapitulatif quotidien"
    AUCUNE = "AUCUNE", "Aucun courriel"


class Intervenant(models.Model):
    """Société ou organisme qui intervient sur le chantier : ses droits (profil, lots).

    Chaque personne y accède avec son propre code (Acces) : on sait qui a déposé, visé ou lu,
    et révoquer un salarié ne coupe pas ses collègues.
    """

    espace = models.ForeignKey(EspaceChantier, on_delete=models.CASCADE, related_name="intervenants")
    entreprise = models.ForeignKey("entreprises.Entreprise", null=True, blank=True, on_delete=models.SET_NULL, related_name="acces_ged")
    nom = models.CharField("société ou organisme", max_length=255)
    profil = models.CharField(max_length=16, choices=Profil.choices, default=Profil.ENTREPRISE)
    lots = models.ManyToManyField("projets.LotProjet", blank=True, related_name="intervenants_ged")
    sous_traitant_de = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="sous_traitants")
    voit_confidentielles = models.BooleanField("voit les pièces chiffrées de ses lots (OS, avenants, devis, situations)", default=True)
    actif = models.BooleanField(default=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["profil", "nom", "id"]

    def __str__(self):
        return self.nom


class Acces(models.Model):
    """Accès personnel d'une personne d'un intervenant : son code, son courriel, ses préférences.

    Le code n'est affiché qu'une fois ; la base n'en garde que l'empreinte. Renvoyer une
    invitation génère un nouveau code pour cette seule personne.
    """

    intervenant = models.ForeignKey(Intervenant, on_delete=models.CASCADE, related_name="acces")
    nom = models.CharField("nom de la personne", max_length=255)
    email = models.EmailField(blank=True)
    frequence = models.CharField("courriels", max_length=12, choices=Frequence.choices, default=Frequence.IMMEDIATE)
    code_empreinte = models.CharField(max_length=64, unique=True)
    code_fin = models.CharField("fin du code (affichage)", max_length=4)
    code_genere_le = models.DateTimeField(default=timezone.now)
    actif = models.BooleanField(default=True)
    dernier_acces = models.DateTimeField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["intervenant", "nom", "id"]
        verbose_name = "accès"
        verbose_name_plural = "accès"

    def __str__(self):
        return f"{self.nom} ({self.intervenant.nom})"


class Zone(models.TextChoices):
    COMMUN = "COMMUN", "Commun à tous"
    LOT = "LOT", "Lot"
    MOE = "MOE", "Maîtrise d'œuvre (réservé)"


class Document(models.Model):
    """Document suivi : plan, fiche, note… Il n'est jamais supprimé, seulement annulé."""

    espace = models.ForeignKey(EspaceChantier, on_delete=models.CASCADE, related_name="documents")
    zone = models.CharField(max_length=6, choices=Zone.choices)
    lot = models.ForeignKey("projets.LotProjet", null=True, blank=True, on_delete=models.CASCADE, related_name="documents_ged")
    categorie = models.CharField(max_length=4, choices=CHOIX_CATEGORIES)
    reference = models.CharField("référence", max_length=60)
    reference_emetteur = models.CharField("n° du cartouche", max_length=80, blank=True)
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


class Diffusion(models.TextChoices):
    POUR_VISA = "VISA", "Pour visa"
    POUR_INFO = "INFO", "Pour information"
    BPE = "BPE", "Bon pour exécution"


class StatutVisa(models.TextChoices):
    SANS_OBJET = "", "—"
    EN_ATTENTE = "EN_ATTENTE", "En attente de visa"
    VSO = "VSO", "Visa sans observation"
    VAO = "VAO", "Visa avec observations"
    REF = "REF", "Refusé : ne pas exécuter"
    HM = "HM", "Hors mission"
    REMPLACE = "REMPLACE", "Remplacé avant visa"


def chemin_version(instance, nom_fichier):
    nom = get_valid_filename(nom_fichier)[-150:]
    document = instance.document
    return f"ged/{document.espace.projet_id}/{document.pk}/{uuid.uuid4().hex[:12]}_{nom}"


def chemin_annexe(instance, nom_fichier):
    nom = get_valid_filename(nom_fichier)[-150:]
    document = instance.version.document if hasattr(instance, "version") else instance.document
    return f"ged/{document.espace.projet_id}/{document.pk}/annexes/{uuid.uuid4().hex[:12]}_{nom}"


class Version(models.Model):
    """Indice d'un document : fichier déposé, objet de la modification, diffusion et visa."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    indice = models.CharField(max_length=4)
    date_indice = models.DateField("date de l'indice (cartouche)", null=True, blank=True)
    fichier = models.FileField(upload_to=chemin_version, max_length=500)
    nom_original = models.CharField(max_length=255)
    taille = models.PositiveBigIntegerField()
    empreinte = models.CharField("SHA-256", max_length=64)
    objet = models.CharField("objet de la modification", max_length=500, blank=True)
    deposee_par_intervenant = models.ForeignKey(Intervenant, null=True, blank=True, on_delete=models.SET_NULL, related_name="versions")
    deposee_par_acces = models.ForeignKey(Acces, null=True, blank=True, on_delete=models.SET_NULL, related_name="versions")
    deposee_par_utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    deposee_par_nom = models.CharField(max_length=255)
    deposee_le = models.DateTimeField(default=timezone.now)
    indice_force = models.CharField("motif d'un indice hors séquence", max_length=300, blank=True)
    diffusion = models.CharField(max_length=4, choices=Diffusion.choices, default=Diffusion.POUR_INFO)
    echeance_visa = models.DateField("date limite de visa", null=True, blank=True)
    visa = models.CharField(max_length=10, choices=StatutVisa.choices, default=StatutVisa.SANS_OBJET, blank=True)
    visa_commentaire = models.TextField("observations du visa", blank=True)
    visa_fichier = models.FileField("plan annoté", upload_to=chemin_annexe, max_length=500, blank=True)
    visa_nom_original = models.CharField(max_length=255, blank=True)
    fiche_visa = models.FileField(upload_to=chemin_annexe, max_length=500, blank=True)
    nouvel_indice_attendu = models.BooleanField(default=False)
    vise_par_nom = models.CharField(max_length=255, blank=True)
    vise_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["document", "-deposee_le", "-id"]
        constraints = [models.UniqueConstraint(fields=["document", "indice"], name="indice_ged_unique")]


class FichierSource(models.Model):
    """Fichier source d'un indice (DWG, IFC, XLSX…) : le fichier de référence visé reste Version.fichier."""

    version = models.ForeignKey(Version, on_delete=models.CASCADE, related_name="sources")
    fichier = models.FileField(upload_to=chemin_annexe, max_length=500)
    nom_original = models.CharField(max_length=255)
    taille = models.PositiveBigIntegerField()
    empreinte = models.CharField("SHA-256", max_length=64)

    class Meta:
        ordering = ["nom_original", "id"]


class RoleAvis(models.TextChoices):
    ARCHITECTE = "ARCHITECTE", "Architecte"
    BET = "BET", "Bureau d'études"
    CONTROLEUR_TECHNIQUE = "CT", "Contrôleur technique"
    CSPS = "CSPS", "Coordonnateur SPS"


class Avis(models.TextChoices):
    VSO = "VSO", "Sans observation"
    VAO = "VAO", "Avec observations"
    REF = "REF", "Défavorable"
    SUSPENDU = "SUSPENDU", "Suspendu (complément attendu)"


class AvisVersion(models.Model):
    """Avis d'un co-traitant ou du contrôleur technique sur un indice, avant le visa de synthèse.

    Les entreprises ne le voient qu'une fois le visa émis par la maîtrise d'œuvre.
    """

    version = models.ForeignKey(Version, on_delete=models.CASCADE, related_name="avis")
    role = models.CharField(max_length=10, choices=RoleAvis.choices)
    avis = models.CharField(max_length=8, choices=Avis.choices)
    observations = models.TextField(blank=True)
    fichier = models.FileField(upload_to=chemin_annexe, max_length=500, blank=True)
    nom_original = models.CharField(max_length=255, blank=True)
    intervenant = models.ForeignKey(Intervenant, null=True, blank=True, on_delete=models.SET_NULL, related_name="avis")
    acces = models.ForeignKey(Acces, null=True, blank=True, on_delete=models.SET_NULL, related_name="avis")
    auteur_nom = models.CharField(max_length=255)
    date = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["date", "id"]


class AccuseLecture(models.Model):
    """Prise de connaissance d'un ordre de service ou d'un avenant par l'entreprise."""

    version = models.ForeignKey(Version, on_delete=models.CASCADE, related_name="accuses")
    intervenant = models.ForeignKey(Intervenant, on_delete=models.CASCADE, related_name="accuses")
    acces = models.ForeignKey(Acces, null=True, blank=True, on_delete=models.SET_NULL, related_name="accuses")
    nom_declare = models.CharField("lu par", max_length=255, blank=True)
    lu_le = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version", "intervenant"], name="accuse_unique")]


class TypeEvenement(models.TextChoices):
    DEPOT = "DEPOT", "Nouveau document"
    INDICE = "INDICE", "Nouvel indice"
    AVIS = "AVIS", "Avis"
    VISA = "VISA", "Visa"
    LECTURE = "LECTURE", "Accusé de lecture"
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
    acces = models.ForeignKey(Acces, null=True, blank=True, on_delete=models.SET_NULL, related_name="evenements")
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    acteur = models.CharField(max_length=255)
    description = models.CharField(max_length=1000)
    adresse_ip = models.GenericIPAddressField(null=True, blank=True)
    navigateur = models.CharField(max_length=300, blank=True)
    depot = models.CharField("identifiant du dépôt groupé", max_length=36, blank=True)
    a_notifier = models.BooleanField(default=False)
    notifie_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["espace", "a_notifier"])]


class Notification(models.Model):
    """Preuve de diffusion : courriel envoyé (ou en échec) à un destinataire pour un événement."""

    evenement = models.ForeignKey(Evenement, on_delete=models.CASCADE, related_name="notifications")
    adresse = models.EmailField()
    acces = models.ForeignKey(Acces, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    envoyee_le = models.DateTimeField(null=True, blank=True)
    erreur = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["evenement", "adresse"]


class StatutArchive(models.TextChoices):
    EN_COURS = "EN_COURS", "En préparation"
    VERIFIEE = "VERIFIEE", "Prête et vérifiée"
    ERREUR = "ERREUR", "Erreur"


class ProjetArchive(models.Model):
    """Archive complète d'un projet (.zip dans le dossier d'archives du cabinet).

    Elle reste listée après la purge des fichiers du projet.
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
    date_reception = models.DateField(null=True, blank=True)
    conserver_jusqu_au = models.DateField(null=True, blank=True)
    demandee_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)
    terminee_le = models.DateTimeField(null=True, blank=True)
    telechargee_le = models.DateTimeField(null=True, blank=True)
    copie_confirmee_le = models.DateTimeField("copie hors du PC confirmée le", null=True, blank=True)
    purge_prevue_le = models.DateTimeField(null=True, blank=True)
    fichiers_purges_le = models.DateTimeField(null=True, blank=True)
    octets_liberes = models.PositiveBigIntegerField(default=0)

    class Meta:
        ordering = ["-cree_le", "-id"]

    def __str__(self):
        return f"Archive {self.nom_projet} ({self.cree_le:%d/%m/%Y})"
