"""Revue de l'étape 4 : archivage, purge, notifications et alertes (constats corrigés)."""
import datetime
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import zipfile
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from comptes.models import Utilisateur
from projets.models import GenrePoste, LotProjet, Poste, Projet
from referentiel.models import Lot

from . import tasks
from .archivage import INTERROMPUE, _plan, motif_refus_purge, produire_archive, purger
from .models import (
    Acces,
    AccuseLecture,
    Document,
    EspaceChantier,
    Evenement,
    Frequence,
    Intervenant,
    Profil,
    ProjetArchive,
    StatutArchive,
    StatutEspace,
    TypeEvenement,
    Version,
    Zone,
)
from .notifications import messages_quotidiens

DOSSIER = tempfile.mkdtemp(prefix="application-ao-revue-archives-")
ARCHIVES = Path(DOSSIER) / "archives"
_compteur = [0]


@override_settings(MEDIA_ROOT=f"{DOSSIER}/fichiers", DOSSIER_ARCHIVES=str(ARCHIVES), GED_DISQUE_LIBRE_MIN_GO=0, EMAIL_ACTIF=True,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RevueArchivageTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER, ignore_errors=True)

    def setUp(self):
        cache.clear()
        shutil.rmtree(ARCHIVES, ignore_errors=True)
        ARCHIVES.mkdir(parents=True)
        self.moe = Utilisateur.objects.create_user("eco", email="eco@cabinet.fr", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE)
        self.client.force_login(self.moe)
        self.projet = Projet.objects.create(nom="Groupe scolaire les Tilleuls", maitre_oeuvre="Atelier A")
        self.lot = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="08"), code="08", intitule="Menuiseries extérieures", ordre=1)
        self.espace = EspaceChantier.objects.create(projet=self.projet, emails_moe="eco@cabinet.fr")

    # --- utilitaires -------------------------------------------------------------
    def document(self, reference="08-EXE-001", titre="Plan de façade", zone=Zone.LOT, categorie="EXE", **champs):
        return Document.objects.create(espace=self.espace, zone=zone, lot=self.lot if zone == Zone.LOT else None, categorie=categorie,
                                       reference=reference, titre=titre, auteur_nom="Durand", **champs)

    def version(self, document, indice="A", **champs):
        _compteur[0] += 1
        contenu = f"%PDF-1.4 plan {_compteur[0]}".encode()
        version = Version(document=document, indice=indice, nom_original="plan.pdf", taille=len(contenu),
                          empreinte=hashlib.sha256(contenu).hexdigest(), deposee_par_nom="Durand", **champs)
        version.fichier.save("plan.pdf", ContentFile(contenu), save=False)
        version.save()
        return version

    def archive(self, statut=StatutArchive.VERIFIEE, il_y_a=datetime.timedelta(0), **champs):
        archive = ProjetArchive.objects.create(projet=self.projet, nom_projet=self.projet.nom, statut=statut, **champs)
        ProjetArchive.objects.filter(pk=archive.pk).update(cree_le=timezone.now() - il_y_a)
        archive.refresh_from_db()
        return archive

    def json(self, methode, url, donnees=None, attendu=200, executer=True):
        with self.captureOnCommitCallbacks(execute=executer):
            reponse = getattr(self.client, methode)(url, json.dumps(donnees or {}), content_type="application/json")
        self.assertEqual(reponse.status_code, attendu, reponse.content)
        return reponse.json() if reponse.content else None

    # --- Constat 9 : la purge n'efface jamais un fichier absent de toute archive -----------------
    def test_purge_refusee_si_documents_deposes_apres_l_archive(self):
        ancien = self.version(self.document(), deposee_le=timezone.now() - datetime.timedelta(days=2))
        archive = self.archive(il_y_a=datetime.timedelta(days=1), nom_fichier="Archive.zip", telechargee_le=timezone.now())
        (ARCHIVES / "Archive.zip").write_bytes(b"PK")
        recent = self.version(self.document("08-DOE-001", "Notice", categorie="DOE"))  # déposé après l'archive
        self.assertIn("refaites une archive", motif_refus_purge(archive))
        self.json("post", f"/api/archives/{archive.pk}/purge", {}, attendu=409)
        # Purge programmée avant le dépôt : la tâche du jour l'annule au lieu d'effacer la notice.
        ProjetArchive.objects.filter(pk=archive.pk).update(purge_prevue_le=timezone.now())
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(purger(archive), 0)
        archive.refresh_from_db()
        self.assertIsNone(archive.purge_prevue_le)
        self.assertIsNone(archive.fichiers_purges_le)
        self.assertIn("refaites une archive", archive.message)
        self.assertTrue(Path(recent.fichier.path).exists() and Path(ancien.fichier.path).exists())
        self.assertEqual(EspaceChantier.objects.get().statut, StatutEspace.OUVERT)
        # Une archive plus récente existe : la purge part de celle-ci, pas de l'ancienne.
        nouvelle = self.archive(nom_fichier="Archive (2).zip", telechargee_le=timezone.now())
        (ARCHIVES / "Archive (2).zip").write_bytes(b"PK")
        self.assertIn("plus récente", motif_refus_purge(archive))
        self.json("post", f"/api/archives/{archive.pk}/purge", {}, attendu=409)
        self.json("post", f"/api/archives/{nouvelle.pk}/purge", {})
        with self.captureOnCommitCallbacks(execute=True):
            self.assertGreater(purger(nouvelle), 0)
        self.assertFalse(Path(recent.fichier.path).exists())

    # --- Constat 12 : date de réception un 29 février -----------------------------------------
    def test_archive_avec_reception_un_29_fevrier(self):
        Poste.objects.create(lot=self.lot, ordre=10, genre=GenrePoste.CHAPITRE, titre="Menuiseries")
        Poste.objects.create(lot=self.lot, ordre=20, titre="Fenêtre", unite="u", quantite=Decimal("10"), prix_unitaire=Decimal("800"))
        EspaceChantier.objects.filter(pk=self.espace.pk).update(date_reception=datetime.date(2028, 2, 29))
        self.version(self.document())
        archive = self.archive(statut=StatutArchive.EN_COURS)
        produire_archive(archive.pk)
        archive.refresh_from_db()
        self.assertEqual(archive.statut, StatutArchive.VERIFIEE, archive.message)
        self.assertEqual(archive.conserver_jusqu_au, datetime.date(2038, 2, 28))

    # --- Constats 3 et 21 : registre de l'archive (formules, noms distincts, liens) -------------
    def test_registre_sans_formule_et_liens_apres_numerotation(self):
        piege = self.document("08-EXE-002", titre='=HYPERLINK("https://x.example/?"&F5,"Voir")', reference_emetteur="=1+1")
        self.version(piege, objet="=2+2")
        longs = [self.document(f"ARC-PRO-PLN-NIV0-00{i}", titre="Plan du niveau zéro", zone=Zone.MOE) for i in (1, 2)]
        for document in longs:
            self.version(document, visa="VSO")
        # Même nom une fois rendu sûr pour Windows : le second est numéroté « (2) ».
        jumeaux = [self.document(reference, titre="Détail", zone=Zone.COMMUN, categorie="PLA") for reference in ("PLA/001", "PLA-001")]
        for document in jumeaux:
            self.version(document)
        archive = self.archive(statut=StatutArchive.EN_COURS)
        with mock.patch("ged.archivage.LONGUEUR_CHEMIN_MAX", 0):  # force les noms les plus courts (16 caractères)
            entrees = _plan(self.projet, archive)
        chemins = [e.chemin for e in entrees]
        noms_longs = [c for c in chemins if "/MOE/" in c]
        self.assertTrue(any("ARC-PRO-PLN-NIV0-001_A_VSO" in c for c in noms_longs), noms_longs)
        self.assertTrue(any("ARC-PRO-PLN-NIV0-002_A_VSO" in c for c in noms_longs), noms_longs)
        registre = next(e for e in entrees if e.chemin == "04 GED/Registre des documents.xlsx").produire()
        with zipfile.ZipFile(io.BytesIO(registre)) as classeur:
            feuille = classeur.read("xl/worksheets/sheet1.xml").decode()
        self.assertNotIn("<f>", feuille)
        self.assertIn("HYPERLINK", feuille)  # le texte reste, en clair
        from openpyxl import load_workbook

        lignes = list(load_workbook(io.BytesIO(registre)).active.iter_rows(min_row=4))
        liens = {ligne[3].value: ligne[14] for ligne in lignes}
        for document in jumeaux:
            self.assertIsNotNone(liens[document.reference].hyperlink)
        cibles = {liens[d.reference].hyperlink.target for d in jumeaux}
        self.assertEqual(len(cibles), 2, cibles)  # chaque ligne ouvre son propre fichier
        self.assertTrue(all(cible[3:] in chemins for cible in cibles), cibles)

    # --- Constats 13 et 38 : archive interrompue --------------------------------------------------
    def test_archive_interrompue_liberee(self):
        perdue = self.archive(statut=StatutArchive.EN_COURS, il_y_a=datetime.timedelta(hours=5))
        abandonne = ARCHIVES / "Archive perdue.zip.partiel"
        abandonne.write_bytes(b"PK")
        ancien = time.time() - 5 * 3600
        os.utime(abandonne, (ancien, ancien))
        en_cours = ARCHIVES / "Archive en cours.zip.partiel"
        en_cours.write_bytes(b"PK")
        # Une nouvelle archive est acceptée : l'ancienne passe en erreur, son .zip.partiel est effacé.
        self.json("post", f"/api/projets/{self.projet.pk}/archives", attendu=201, executer=False)
        perdue.refresh_from_db()
        self.assertEqual((perdue.statut, perdue.message), (StatutArchive.ERREUR, INTERROMPUE))
        self.assertFalse(abandonne.exists())
        self.assertTrue(en_cours.exists())  # récent : peut-être une archive en cours d'écriture
        # Celle qui vient d'être demandée reste « en préparation » : une seconde demande est refusée.
        self.json("post", f"/api/projets/{self.projet.pk}/archives", attendu=409, executer=False)
        # Le worker « voix » ne touche à rien ; le worker principal libère tout à son démarrage.
        tasks._archives_interrompues(sender=mock.Mock(hostname="voix@pc"))
        self.assertTrue(ProjetArchive.objects.filter(statut=StatutArchive.EN_COURS).exists())
        tasks._archives_interrompues(sender=mock.Mock(hostname="celery@pc"))
        self.assertFalse(ProjetArchive.objects.filter(statut=StatutArchive.EN_COURS).exists())
        self.assertFalse(en_cours.exists())

    def test_archive_en_erreur_si_mise_en_file_impossible(self):
        with mock.patch("ged.api_archives.produire_archive") as tache:
            tache.delay.side_effect = ConnectionError("Redis injoignable")
            archive = self.json("post", f"/api/projets/{self.projet.pk}/archives", attendu=201)
        self.assertEqual(ProjetArchive.objects.get(pk=archive["id"]).statut, StatutArchive.ERREUR)

    # --- Constat 14 : relance des OS -------------------------------------------------------------
    def test_relance_des_os_ni_sous_traitant_ni_aucun_courriel(self):
        titulaire = Intervenant.objects.create(espace=self.espace, nom="Menuiseries Durand", profil=Profil.ENTREPRISE)
        sous_traitant = Intervenant.objects.create(espace=self.espace, nom="Pose Express", profil=Profil.ENTREPRISE, voit_confidentielles=False)
        for intervenant in (titulaire, sous_traitant):
            intervenant.lots.add(self.lot)
        for intervenant, nom, email, frequence in ((titulaire, "Paul", "paul@durand.fr", Frequence.IMMEDIATE),
                                                   (titulaire, "Jean", "jean@durand.fr", Frequence.AUCUNE),
                                                   (sous_traitant, "Luc", "luc@pose.fr", Frequence.IMMEDIATE)):
            Acces.objects.create(intervenant=intervenant, nom=nom, email=email, frequence=frequence, code_empreinte=email, code_fin="AAAA")
        os_ = self.version(self.document("08-OS-001", "Travaux supplémentaires", categorie="OS"))
        relances = [m for m in messages_quotidiens(self.espace) if "Ordres de service" in m.subject]
        self.assertEqual([m.to for m in relances], [["paul@durand.fr"]])
        AccuseLecture.objects.create(version=os_, intervenant=titulaire)
        self.assertEqual([m for m in messages_quotidiens(self.espace) if "Ordres de service" in m.subject], [])

    # --- Constats 11 et 24 : récapitulatif du matin -----------------------------------------------
    def test_recapitulatif_du_lundi_couvre_le_week_end(self):
        moa = Intervenant.objects.create(espace=self.espace, nom="Ville", profil=Profil.MAITRE_OUVRAGE)
        Acces.objects.create(intervenant=moa, nom="Service bâtiments", email="moa@ville.fr", frequence=Frequence.QUOTIDIENNE, code_empreinte="moa", code_fin="AAAA")
        lundi = timezone.make_aware(datetime.datetime(2026, 11, 9, 7, 0))
        for quand, description in ((lundi - datetime.timedelta(days=2, hours=21), "Plan du vendredi"),
                                   (lundi - datetime.timedelta(hours=1), "Plan du lundi matin"),
                                   (lundi + datetime.timedelta(hours=8), "Plan du lundi après-midi")):
            Evenement.objects.create(espace=self.espace, type=TypeEvenement.DEPOT, date=quand, acteur="Durand", description=description)

        def recapitulatif(maintenant):
            mail.outbox.clear()
            with mock.patch("ged.tasks.timezone") as horloge:
                horloge.now.return_value = maintenant
                horloge.localdate.return_value = timezone.localtime(maintenant).date()
                tasks.recapitulatif_quotidien()
            return next(m for m in mail.outbox if m.to == ["moa@ville.fr"]).body

        corps = recapitulatif(lundi)
        self.assertIn("Plan du vendredi", corps)  # vendredi 10 h : couvert le lundi
        self.assertIn("Plan du lundi matin", corps)
        self.assertNotIn("Plan du lundi après-midi", corps)
        self.assertIn("depuis le précédent récapitulatif", corps)
        # Le mardi reprend exactement là où le lundi s'est arrêté.
        corps = recapitulatif(lundi + datetime.timedelta(days=1))
        self.assertEqual((corps.count("Plan du"), "Plan du lundi après-midi" in corps), (1, True))

    def test_recapitulatif_un_seul_envoi_pour_tous_les_chantiers(self):
        autre = Projet.objects.create(nom="Collège Jean Moulin")
        EspaceChantier.objects.create(projet=autre, emails_moe="eco@cabinet.fr")
        Version.objects.filter(pk=self.version(self.document(), diffusion="VISA", visa="EN_ATTENTE").pk).update(echeance_visa=timezone.localdate())
        with mock.patch("ged.tasks.envoyer", return_value=0) as envoyer:
            tasks.recapitulatif_quotidien()
        self.assertEqual(envoyer.call_count, 1)
        paquets = envoyer.call_args.args[0]
        self.assertTrue(any("Visas à rendre" in message.subject and evenements == [] for message, evenements, _ in paquets))

    # --- Constats 19 et 23 : relance et regroupement des notifications ---------------------------
    def test_relance_une_tache_par_espace(self):
        for minutes in (10, 9, 8):
            Evenement.objects.create(espace=self.espace, type=TypeEvenement.DEPOT, date=timezone.now() - datetime.timedelta(minutes=minutes),
                                     acteur="Durand", description="Plan", a_notifier=True)
        with mock.patch("ged.tasks.notifier_espace") as tache:
            tasks.relancer_notifications()
        self.assertEqual(tache.delay.call_count, 1)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_regroupement_limite_a_30_minutes(self):
        notifier = tasks.notifier_espace
        maintenant = timezone.now()
        for minutes in (8, 1):
            Evenement.objects.create(espace=self.espace, type=TypeEvenement.DEPOT, date=maintenant - datetime.timedelta(minutes=minutes),
                                     acteur="Durand", description="Plan", a_notifier=True)
        with mock.patch("ged.tasks.notifier_espace") as tache, self.captureOnCommitCallbacks(execute=True):
            notifier(self.espace.pk)
        self.assertEqual(tache.apply_async.call_count, 1)  # dépôt en cours : on attend le calme
        premier = Evenement.objects.filter(espace=self.espace).order_by("date").first()
        Evenement.objects.filter(pk=premier.pk).update(date=maintenant - datetime.timedelta(minutes=40))
        with mock.patch("ged.tasks.notifier_espace") as tache, self.captureOnCommitCallbacks(execute=True):
            notifier(self.espace.pk)
        self.assertEqual(tache.apply_async.call_count, 0)  # activité continue depuis 40 minutes : envoi
        self.assertFalse(Evenement.objects.filter(espace=self.espace, notifie_le__isnull=True).exists())

    # --- Constats 4, 8 et 44 : essais erronés ------------------------------------------------------
    def test_alerte_des_essais_selon_la_fiabilite_des_adresses(self):
        from .acces import MESSAGE_REFUS, SEUIL_ALERTE, noter_echec

        self.assertIn("espace du chantier clos", MESSAGE_REFUS)
        cache.set("ged:echecs:total", SEUIL_ALERTE - 1, 3600)
        requete = RequestFactory().post("/api/ged/acces", REMOTE_ADDR="172.17.0.1")
        with override_settings(GED_IP_FIABLE=False), mock.patch("ged.tasks.alerter_essais") as alerte, mock.patch("time.sleep") as attente:
            noter_echec(requete)
        alerte.delay.assert_called_once_with(SEUIL_ALERTE, False)
        attente.assert_not_called()  # jamais d'attente dans le fil de la requête
        tasks.alerter_essais(SEUIL_ALERTE, False)
        self.assertIn("ne permet pas de les identifier", mail.outbox[-1].body)
        tasks.alerter_essais(SEUIL_ALERTE, True)
        self.assertIn("indique les adresses concernées", mail.outbox[-1].body)
