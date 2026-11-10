"""Tests de la sauvegarde, sans PostgreSQL : pg_dump, pg_restore, createdb, dropdb et psql sont simulés
(subprocess.run remplacé), ainsi que l'instantané et le comptage des lignes."""
import contextlib
import datetime
import errno
import json
import os
import shutil
import subprocess
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from comptes.models import Utilisateur

from . import services
from .miroir import DELAI_SUPPRESSION, miroir
from .models import Sauvegarde, StatutSauvegarde
from .postgres import ErreurSauvegarde
from .services import INTERROMPUE, alerte, etat, lancer, rotation, sur_le_meme_disque
from .tasks import _sauvegardes_interrompues, sauvegarder

PARAMETRES = {"dbname": "application_ao", "user": "application_ao", "password": "mot-de-passe-pg", "host": "base", "port": "5432"}
COMPTES = {"projets_projet": 3, "ged_document": 12, "ged_version": 20, "django_migrations": 60}
CLES_ETAT = {"derniere", "derniere_reussie", "en_cours", "destination", "stockage_serveur", "alerte", "heure"}


class FauxOutils:
    """Remplace subprocess.run : note les commandes, écrit le fichier de pg_dump, échoue sur demande."""

    def __init__(self):
        self.commandes: list[list[str]] = []
        self.environnements: list[dict] = []
        self.echecs: dict[str, str] = {}
        self.scripts_lus: list[str] = []  # contenu du script SQL quand psql le rejoue

    def __call__(self, commande, env=None, **_options):
        self.commandes.append(list(commande))
        self.environnements.append(env or {})
        if commande[0] in self.echecs:
            return subprocess.CompletedProcess(commande, 1, "", self.echecs[commande[0]])
        fichier = next((argument.split("=", 1)[1] for argument in commande if argument.startswith("--file=")), None)
        if commande[0] == "pg_dump":
            Path(fichier).write_bytes(b"PGDMP" + b"\0" * 2048)
        elif commande[0] == "pg_restore" and fichier:  # conversion de la copie en script SQL
            Path(fichier).write_text("CREATE TABLE public.projets_projet (id bigint);\n", encoding="utf-8")
        elif commande[0] == "psql":
            self.scripts_lus.append(Path(commande[commande.index("-f") + 1]).read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(commande, 0, "", "")

    def outils(self) -> list[str]:
        return [commande[0] for commande in self.commandes]


class OutilsSimules:
    """Dossiers temporaires et outils PostgreSQL simulés pour chaque test."""

    def setUp(self):
        super().setUp()
        self.racine = Path(tempfile.mkdtemp(prefix="daplomb-sauvegardes-"))
        self.addCleanup(shutil.rmtree, self.racine, ignore_errors=True)
        self.fichiers, self.archives, self.sauvegardes = self.racine / "fichiers", self.racine / "archives", self.racine / "sauvegardes"
        (self.fichiers / "ged" / "3").mkdir(parents=True)
        self.archives.mkdir()
        (self.fichiers / "ged" / "3" / "plan.pdf").write_bytes(b"%PDF plan")
        (self.archives / "Chantier.zip").write_bytes(b"PK archive")
        self.env = self.racine / "configuration" / ".env"
        self.env.parent.mkdir()
        self.env.write_text("DJANGO_SECRET_KEY=cle-des-codes-ged\nPOSTGRES_PASSWORD=x\n", encoding="utf-8")
        reglages = override_settings(
            MEDIA_ROOT=str(self.fichiers), DOSSIER_ARCHIVES=self.archives, DOSSIER_SAUVEGARDES=self.sauvegardes,
            FICHIER_CONFIGURATION=self.env, STOCKAGE_SERVEUR=False, DOSSIER_SAUVEGARDES_PC="D:\\Sauvegardes",
            DOSSIER_SAUVEGARDES_AFFICHE="D:\\Sauvegardes", SERVEUR_CHEMIN_AFFICHE="", EMAIL_ACTIF=False,
        )
        reglages.enable()
        self.addCleanup(reglages.disable)
        self.outils = FauxOutils()
        self.comptes_restaures = dict(COMPTES)

        @contextlib.contextmanager
        def faux_instantane(_p):
            yield "00000003-0000001B-1", dict(COMPTES)

        for cible, remplacement in (
            ("sauvegardes.postgres.subprocess.run", self.outils),
            ("sauvegardes.postgres.parametres", lambda: dict(PARAMETRES)),
            ("sauvegardes.postgres.instantane", faux_instantane),
            ("sauvegardes.postgres.compter_base", lambda _p, _base: dict(self.comptes_restaures)),
        ):
            patcher = mock.patch(cible, remplacement)
            patcher.start()
            self.addCleanup(patcher.stop)


class SauvegardeTests(OutilsSimules, TestCase):
    def test_sauvegarde_complete_verifiee(self):
        sauvegarde = lancer("essai")
        self.assertEqual(sauvegarde.statut, StatutSauvegarde.REUSSIE, sauvegarde.message)
        self.assertTrue(sauvegarde.verifiee)
        self.assertRegex(sauvegarde.fichier, r"^base/\d{4}-\d{2}-\d{2}_\d{4}\.dump$")
        copie = self.sauvegardes / sauvegarde.fichier
        self.assertTrue(copie.is_file())
        self.assertEqual(sauvegarde.taille, copie.stat().st_size)
        self.assertEqual(list(self.sauvegardes.rglob("*.partiel")), [])
        # a) pg_dump au format personnalisé, sur l'instantané compté, dans un .partiel renommé ensuite.
        pg_dump = self.outils.commandes[0]
        self.assertEqual(pg_dump[0], "pg_dump")
        self.assertIn("--format=custom", pg_dump)
        self.assertIn("--snapshot=00000003-0000001B-1", pg_dump)
        self.assertTrue(any(a.startswith("--file=") and a.endswith(".dump.partiel") for a in pg_dump))
        # b) restauration d'essai dans la base temporaire, supprimée ensuite.
        self.assertEqual(self.outils.outils(), ["pg_dump", "dropdb", "createdb", "pg_restore", "dropdb"])
        pg_restore = self.outils.commandes[3]
        self.assertIn("--dbname=verification_sauvegarde", pg_restore)
        self.assertIn("--exit-on-error", pg_restore)
        self.assertNotIn("--clean", pg_restore)
        self.assertEqual(self.outils.commandes[-1][-1], "verification_sauvegarde")
        # Le mot de passe passe par l'environnement, jamais par la ligne de commande.
        self.assertTrue(all("mot-de-passe-pg" not in " ".join(c) for c in self.outils.commandes))
        self.assertEqual(self.outils.environnements[0]["PGPASSWORD"], "mot-de-passe-pg")
        # c) configuration ; d) miroir des fichiers et des archives.
        self.assertEqual((self.sauvegardes / "configuration" / ".env").read_bytes(), self.env.read_bytes())
        self.assertEqual((self.sauvegardes / "fichiers" / "ged" / "3" / "plan.pdf").read_bytes(), b"%PDF plan")
        self.assertEqual((self.sauvegardes / "archives" / "Chantier.zip").read_bytes(), b"PK archive")
        self.assertEqual(sauvegarde.fichiers_copies, 2)
        self.assertTrue((self.sauvegardes / "LISEZ-MOI.txt").is_file())
        self.assertIn("vérifiée par une restauration d’essai (4 tables, 95 lignes)", sauvegarde.message)
        self.assertEqual(len(mail.outbox), 0)

    def test_deuxieme_sauvegarde_ne_recopie_que_le_nouveau(self):
        lancer("essai")
        (self.fichiers / "ged" / "3" / "plan-B.pdf").write_bytes(b"%PDF plan B")
        seconde = lancer("essai")
        self.assertEqual(seconde.statut, StatutSauvegarde.REUSSIE, seconde.message)
        self.assertEqual(seconde.fichiers_copies, 1)
        self.assertIn("Configuration (.env) déjà à jour.", seconde.message)
        self.assertEqual(len(list((self.sauvegardes / "base").glob("*.dump"))), 2)  # même minute : nom suffixé

    @override_settings(EMAIL_ACTIF=True, URL_APPLICATION="http://192.168.1.20:8080")
    def test_echec_de_pg_dump_courriel_aux_administrateurs(self):
        Utilisateur.objects.create_superuser("admin", "admin@cabinet.fr", "mot-de-passe-solide-42")
        Utilisateur.objects.create_user("gerante", email="gerante@cabinet.fr", password="mot-de-passe-solide-42", role=Utilisateur.Role.ADMINISTRATEUR)
        Utilisateur.objects.create_user("eco", email="eco@cabinet.fr", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE)
        Utilisateur.objects.create_superuser("ancien", "ancien@cabinet.fr", "mot-de-passe-solide-42", is_active=False)
        Utilisateur.objects.create_superuser("sans-adresse", "", "mot-de-passe-solide-42")
        (self.sauvegardes / "base").mkdir(parents=True)
        ancienne = self.sauvegardes / "base" / "2020-01-01_0230.dump"
        ancienne.write_bytes(b"PGDMP ancienne")
        self.outils.echecs["pg_dump"] = "pg_dump: error: connection to server at \"base\" failed: Connection refused"
        sauvegarde = lancer("planification")
        self.assertEqual(sauvegarde.statut, StatutSauvegarde.ECHEC)
        self.assertFalse(sauvegarde.verifiee)
        self.assertIn("Connection refused", sauvegarde.message)
        self.assertNotIn("pg_restore", self.outils.outils())  # pas de restauration d'essai sans copie
        self.assertTrue(ancienne.exists())  # pas de rotation après un échec
        self.assertEqual(list(self.sauvegardes.rglob("*.partiel")), [])
        # Les autres étapes ont été faites quand même.
        self.assertTrue((self.sauvegardes / "configuration" / ".env").exists())
        self.assertTrue((self.sauvegardes / "fichiers" / "ged" / "3" / "plan.pdf").exists())
        self.assertEqual(len(mail.outbox), 1)
        courriel = mail.outbox[0]
        self.assertEqual(sorted(courriel.to), ["admin@cabinet.fr", "gerante@cabinet.fr"])
        self.assertIn("a échoué", courriel.subject)
        self.assertIn("Connection refused", courriel.body)
        self.assertIn("D:\\Sauvegardes", courriel.body)
        self.assertIn("http://192.168.1.20:8080", courriel.body)
        self.assertIn("a échoué", etat()["alerte"])

    def test_pas_de_courriel_sans_messagerie(self):
        Utilisateur.objects.create_superuser("admin", "admin@cabinet.fr", "mot-de-passe-solide-42")
        self.outils.echecs["pg_dump"] = "pg_dump: error"
        self.assertEqual(lancer("planification").statut, StatutSauvegarde.ECHEC)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_ACTIF=True)
    def test_restauration_d_essai_differente(self):
        Utilisateur.objects.create_superuser("admin", "admin@cabinet.fr", "mot-de-passe-solide-42")
        self.comptes_restaures["ged_version"] = 19
        sauvegarde = lancer("planification")
        self.assertEqual(sauvegarde.statut, StatutSauvegarde.REUSSIE, sauvegarde.message)
        self.assertFalse(sauvegarde.verifiee)
        self.assertIn("NON VÉRIFIÉE", sauvegarde.message)
        self.assertIn("ged_version (19 lignes au lieu de 20)", sauvegarde.message)
        self.assertEqual(self.outils.outils()[-1], "dropdb")  # base d'essai supprimée malgré l'écart
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("non vérifiée", mail.outbox[0].subject)
        self.assertIn("n’a pas pu être vérifiée", etat()["alerte"])

    @override_settings(EMAIL_ACTIF=True)
    def test_courriel_copie_non_verifiee_conseil(self):
        """Copie écrite mais restauration d'essai en échec : le conseil vise le disque de Docker du PC, jamais le
        serveur ni le dossier des sauvegardes (où la copie vient d'être écrite)."""
        Utilisateur.objects.create_superuser("admin", "admin@cabinet.fr", "mot-de-passe-solide-42")
        self.outils.echecs["pg_restore"] = ("pg_restore: error: could not execute query: ERROR: could not extend file "
                                            "\"base/16384/16390\": No space left on device")
        for stockage_serveur in (True, False):
            with self.subTest(stockage_serveur=stockage_serveur), override_settings(STOCKAGE_SERVEUR=stockage_serveur):
                mail.outbox.clear()
                sauvegarde = lancer("planification")
                self.assertEqual(sauvegarde.statut, StatutSauvegarde.REUSSIE, sauvegarde.message)
                self.assertFalse(sauvegarde.verifiee)
                self.assertEqual(len(mail.outbox), 1)
                courriel = mail.outbox[0]
                self.assertEqual(courriel.subject, "D’Aplomb : sauvegarde non vérifiée")
                self.assertIn("No space left on device", courriel.body)
                self.assertIn("La copie a bien été écrite dans le dossier des sauvegardes", courriel.body)
                self.assertIn("disque du PC de l’application qui contient Docker", courriel.body)
                self.assertNotIn("joignable depuis le PC", courriel.body)
                self.assertNotIn("dossier des sauvegardes est accessible", courriel.body)
                self.assertNotIn("ne sont plus protégées", courriel.body)
        # Un vrai échec en mode serveur garde le conseil sur le serveur de l'agence.
        self.outils.echecs = {"pg_dump": "pg_dump: error: could not open output file: Host is down"}
        mail.outbox.clear()
        with override_settings(STOCKAGE_SERVEUR=True):
            self.assertEqual(lancer("planification").statut, StatutSauvegarde.ECHEC)
        self.assertEqual(mail.outbox[0].subject, "D’Aplomb : la sauvegarde a échoué")
        self.assertIn("joignable depuis le PC de l’application", mail.outbox[0].body)
        self.assertNotIn("contient Docker", mail.outbox[0].body)

    def test_restauration_d_essai_en_erreur(self):
        self.outils.echecs["pg_restore"] = "pg_restore: error: could not read from input file: end of file"
        sauvegarde = lancer("planification")
        self.assertFalse(sauvegarde.verifiee)
        self.assertIn("end of file", sauvegarde.message)
        self.assertEqual(self.outils.outils()[-1], "dropdb")

    def test_configuration_absente(self):
        self.env.unlink()
        sauvegarde = lancer("planification")
        self.assertEqual(sauvegarde.statut, StatutSauvegarde.ECHEC)
        self.assertIn("clé des codes d’accès de la GED", sauvegarde.message)
        self.assertTrue(sauvegarde.verifiee)  # la base est sauvegardée quand même

    def test_configuration_remplacee_gardee_dans_l_historique(self):
        lancer("essai")
        # Un autre réglage change, même clé : la copie est remplacée, l'ancienne version gardée.
        self.env.write_text("DJANGO_SECRET_KEY=cle-des-codes-ged\nPOSTGRES_PASSWORD=y\n", encoding="utf-8")
        sauvegarde = lancer("essai")
        self.assertIn("Configuration (.env) copiée.", sauvegarde.message)
        copie = self.sauvegardes / "configuration"
        self.assertEqual((copie / ".env").read_bytes(), self.env.read_bytes())
        historique = list((copie / "historique").iterdir())
        self.assertEqual(len(historique), 1)
        self.assertTrue(historique[0].name.startswith("remplace-le-"))
        self.assertIn("POSTGRES_PASSWORD=x", historique[0].read_text(encoding="utf-8"))
        self.assertEqual(etat()["alerte"], "")

    def test_configuration_avec_une_autre_cle_jamais_remplacee(self):
        from .management.commands.restaurer import cle_sauvegardee

        lancer("essai")
        copie = self.sauvegardes / "configuration"
        ancien = (copie / ".env").read_bytes()
        # .env régénéré par installer.ps1 (nouveau PC, avant la restauration) : nouvelle clé.
        self.env.write_text('DJANGO_SECRET_KEY="nouvelle-cle"\nPOSTGRES_PASSWORD=x\n', encoding="utf-8")
        sauvegarde = lancer("essai")
        self.assertEqual(sauvegarde.statut, StatutSauvegarde.REUSSIE, sauvegarde.message)  # la base est sauvegardée
        self.assertTrue(sauvegarde.verifiee)
        self.assertEqual((copie / ".env").read_bytes(), ancien)
        self.assertEqual(cle_sauvegardee(), "cle-des-codes-ged")  # restaurer.ps1 et restaurer préviennent toujours
        nouvelles = list((copie / "historique").iterdir())
        self.assertEqual([f.name[:13] for f in nouvelles], ["nouvelle-cle-"])
        self.assertEqual(nouvelles[0].read_bytes(), self.env.read_bytes())
        self.assertIn("ATTENTION, la clé DJANGO_SECRET_KEY du .env de l’application diffère", sauvegarde.message)
        self.assertIn(f"configuration\\historique\\{nouvelles[0].name}", sauvegarde.message)
        self.assertIn("La clé DJANGO_SECRET_KEY de l’application diffère", etat()["alerte"])
        self.assertIn("restaurer.ps1", etat()["alerte"])
        # Nuit suivante : l'écart est encore signalé, sans seconde copie du même fichier.
        self.assertIn("ATTENTION", lancer("essai").message)
        self.assertEqual(len(list((copie / "historique").iterdir())), 1)
        # Changement voulu : configuration\.env supprimé à la main, le nouveau est copié et l'alerte disparaît.
        (copie / ".env").unlink()
        self.assertIn("Configuration (.env) copiée.", lancer("essai").message)
        self.assertEqual((copie / ".env").read_bytes(), self.env.read_bytes())
        self.assertEqual(etat()["alerte"], "")

    @override_settings(SAUVEGARDE_JOURS=1, SAUVEGARDE_MOIS=0)
    def test_rotation_n_efface_que_les_copies_de_cette_base(self):
        # Base neuve (Docker réinitialisé, nouveau PC) : la copie du jour, faite par l'ancienne base et inconnue
        # de celle-ci, contient les vraies données. Elle n'est pas effacée, même si elle sort de la rotation.
        base = self.sauvegardes / "base"
        base.mkdir(parents=True)
        aujourd_hui = timezone.localtime()
        autre = base / f"{aujourd_hui:%Y-%m-%d}_0000.dump"
        autre.write_bytes(b"PGDMP vraies donnees")
        connue = base / f"{aujourd_hui - datetime.timedelta(days=1):%Y-%m-%d}_0230.dump"
        connue.write_bytes(b"PGDMP")
        Sauvegarde.objects.create(debut=timezone.now() - datetime.timedelta(days=1), statut=StatutSauvegarde.REUSSIE,
                                  fichier=f"base/{connue.name}")
        sauvegarde = lancer("essai")
        self.assertEqual(sauvegarde.statut, StatutSauvegarde.REUSSIE, sauvegarde.message)
        self.assertTrue(autre.exists())
        self.assertFalse(connue.exists())  # copie de cette base hors des jours gardés : effacée
        self.assertTrue((self.sauvegardes / sauvegarde.fichier).exists())
        self.assertIn("1 ancienne(s) copie(s) de la base effacée(s).", sauvegarde.message)
        self.assertIn("1 ancienne(s) copie(s) de la base faite(s) par une autre installation ou avant une restauration, "
                      "conservée(s)", sauvegarde.message)

    def test_dossier_des_sauvegardes_injoignable(self):
        bloquant = self.racine / "fichier-ordinaire"
        bloquant.write_text("x")
        with override_settings(DOSSIER_SAUVEGARDES=bloquant / "sauvegardes"):
            sauvegarde = lancer("planification")
        self.assertEqual(sauvegarde.statut, StatutSauvegarde.ECHEC)
        self.assertIn("D:\\Sauvegardes inaccessible", sauvegarde.message)
        self.assertEqual(self.outils.commandes, [])

    def test_fichiers_sur_le_serveur_pas_de_miroir(self):
        with override_settings(STOCKAGE_SERVEUR=True, SERVEUR_CHEMIN_AFFICHE="\\\\SERVEUR\\DAplomb"):
            sauvegarde = lancer("planification")
            self.assertEqual(sauvegarde.statut, StatutSauvegarde.REUSSIE, sauvegarde.message)
            self.assertEqual(sauvegarde.fichiers_copies, 0)
            self.assertFalse((self.sauvegardes / "fichiers").exists())
            self.assertFalse((self.sauvegardes / "archives").exists())
            self.assertIn("déjà sur le serveur", sauvegarde.message)
            self.assertTrue((self.sauvegardes / "configuration" / ".env").exists())
            reponse = etat()
            self.assertEqual(reponse["destination"], "\\\\SERVEUR\\DAplomb\\sauvegardes")
            self.assertTrue(reponse["stockage_serveur"])
            self.assertEqual(reponse["alerte"], "")

    def test_erreur_inattendue_ne_laisse_pas_la_sauvegarde_en_cours(self):
        with mock.patch("sauvegardes.postgres.parametres", side_effect=[dict(PARAMETRES), RuntimeError("panne imprévue")]):
            sauvegarde = lancer("planification")
        self.assertEqual(sauvegarde.statut, StatutSauvegarde.ECHEC)
        self.assertIn("Erreur inattendue (RuntimeError : panne imprévue)", sauvegarde.message)
        self.assertIsNotNone(sauvegarde.fin)

    def test_une_seule_sauvegarde_a_la_fois(self):
        with services.verrou() as obtenu:
            self.assertTrue(obtenu)
            self.assertIsNone(lancer("planification"))
        self.assertEqual(Sauvegarde.objects.count(), 0)
        self.assertIsNotNone(lancer("planification"))

    def test_sauvegardes_interrompues(self):
        ancienne = Sauvegarde.objects.create(debut=timezone.now() - datetime.timedelta(hours=7))
        recente = Sauvegarde.objects.create(declenchee_par="admin")
        reponse = etat()
        ancienne.refresh_from_db()
        self.assertEqual(ancienne.statut, StatutSauvegarde.ECHEC)
        self.assertEqual(ancienne.message, INTERROMPUE)
        self.assertTrue(reponse["en_cours"])
        # Au redémarrage du worker, la demande en attente est notée interrompue… puis faite par sa tâche.
        _sauvegardes_interrompues(sender=None)
        recente.refresh_from_db()
        self.assertEqual(recente.statut, StatutSauvegarde.ECHEC)
        sauvegarder(recente.pk, "admin")
        recente.refresh_from_db()
        self.assertEqual(recente.statut, StatutSauvegarde.REUSSIE, recente.message)
        self.assertEqual(Sauvegarde.objects.count(), 2)

    def test_la_planification_laisse_passer_une_demande_en_attente(self):
        Sauvegarde.objects.create(declenchee_par="admin")
        sauvegarder()
        self.assertEqual(Sauvegarde.objects.count(), 1)
        self.assertEqual(self.outils.commandes, [])


class MiroirTests(TestCase):
    def setUp(self):
        self.racine = Path(tempfile.mkdtemp(prefix="daplomb-miroir-"))
        self.addCleanup(shutil.rmtree, self.racine, ignore_errors=True)
        self.source, self.copie, self.manifeste = self.racine / "source", self.racine / "copie", self.racine / "manifestes" / "fichiers.json"
        (self.source / "ged" / "3").mkdir(parents=True)
        (self.source / "ged" / "3" / "a.pdf").write_bytes(b"A")
        (self.source / "ged" / "3" / "b.pdf").write_bytes(b"BB")
        (self.source / "ged" / "4").mkdir()
        (self.source / "ged" / "4" / "c.pdf").write_bytes(b"CCC")
        self.t0 = timezone.now()

    def passe(self, decalage_jours=0, **options):
        return miroir(self.source, self.copie, self.t0 + datetime.timedelta(days=decalage_jours), manifeste=self.manifeste, **options)

    def test_copie_des_nouveaux_et_des_modifies_seulement(self):
        self.assertEqual(self.passe().copies, 3)
        self.assertEqual(self.passe().copies, 0)
        (self.source / "ged" / "3" / "a.pdf").write_bytes(b"A modifie")
        bilan = self.passe()
        self.assertEqual(bilan.copies, 1)
        self.assertEqual((self.copie / "ged" / "3" / "a.pdf").read_bytes(), b"A modifie")
        # Même taille mais date différente : recopié.
        chemin = self.source / "ged" / "3" / "b.pdf"
        chemin.write_bytes(b"XY")
        os.utime(chemin, (chemin.stat().st_atime, chemin.stat().st_mtime + 3600))
        self.assertEqual(self.passe().copies, 1)
        self.assertEqual((self.copie / "ged" / "3" / "b.pdf").read_bytes(), b"XY")

    def test_suppression_differee_de_30_jours(self):
        self.passe()
        (self.source / "ged" / "4" / "c.pdf").unlink()
        bilan = self.passe(1)
        self.assertEqual((bilan.en_attente, bilan.supprimes), (1, 0))
        self.assertTrue((self.copie / "ged" / "4" / "c.pdf").exists())
        manifeste = json.loads(self.manifeste.read_text(encoding="utf-8"))
        self.assertIn("ged/4/c.pdf", manifeste["disparus"])
        bilan = self.passe(1 + DELAI_SUPPRESSION.days - 1)  # le délai court depuis la disparition constatée
        self.assertEqual((bilan.en_attente, bilan.supprimes), (1, 0))
        self.assertTrue((self.copie / "ged" / "4" / "c.pdf").exists())
        bilan = self.passe(1 + DELAI_SUPPRESSION.days)
        self.assertEqual((bilan.en_attente, bilan.supprimes), (0, 1))
        self.assertFalse((self.copie / "ged" / "4").exists())  # dossier vidé supprimé
        self.assertEqual(json.loads(self.manifeste.read_text(encoding="utf-8"))["disparus"], {})
        self.assertTrue((self.copie / "ged" / "3" / "a.pdf").exists())

    def test_fichier_revenu_retire_du_manifeste(self):
        self.passe()
        (self.source / "ged" / "3" / "b.pdf").unlink()
        self.assertEqual(self.passe(2).en_attente, 1)
        (self.source / "ged" / "3" / "b.pdf").write_bytes(b"BB de retour")
        bilan = self.passe(40)
        self.assertEqual((bilan.en_attente, bilan.supprimes, bilan.copies), (0, 0, 1))
        self.assertEqual((self.copie / "ged" / "3" / "b.pdf").read_bytes(), b"BB de retour")

    def test_source_vide_aucune_suppression(self):
        self.passe()
        shutil.rmtree(self.source / "ged")
        bilan = self.passe(60)
        self.assertIn("vide", bilan.suppressions_suspendues)
        self.assertEqual((bilan.en_attente, bilan.supprimes), (0, 0))
        self.assertTrue((self.copie / "ged" / "3" / "a.pdf").exists())
        shutil.rmtree(self.source)
        self.assertIn("introuvable", self.passe(90).suppressions_suspendues)
        self.assertTrue((self.copie / "ged" / "3" / "a.pdf").exists())

    def test_partiels_et_dossiers_exclus_ignores(self):
        (self.source / "archives").mkdir()
        (self.source / "archives" / "x.zip").write_bytes(b"zip")
        (self.source / "en-cours.zip.partiel").write_bytes(b"incomplet")
        self.copie.mkdir()
        (self.copie / "reste.pdf.partiel").write_bytes(b"copie interrompue")
        bilan = self.passe(exclus=(self.source / "archives",))
        self.assertEqual(bilan.copies, 3)
        self.assertFalse((self.copie / "archives").exists())
        self.assertFalse((self.copie / "en-cours.zip.partiel").exists())
        self.assertFalse((self.copie / "reste.pdf.partiel").exists())

    def test_sans_suppression_pour_la_recopie(self):
        self.passe()
        (self.copie / "en-plus.pdf").write_bytes(b"garde")
        bilan = miroir(self.source, self.copie, self.t0 + datetime.timedelta(days=90), supprimer=False)
        self.assertEqual(bilan.supprimes, 0)
        self.assertTrue((self.copie / "en-plus.pdf").exists())

    def test_disque_plein(self):
        with mock.patch("sauvegardes.miroir.shutil.copyfile", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            with self.assertRaisesMessage(ErreurSauvegarde, "plus de place dans le dossier des sauvegardes (0 fichiers copiés)."):
                self.passe()
            with self.assertRaisesMessage(ErreurSauvegarde, "plus de place sur le disque de l’application (0 fichiers copiés)."):
                self.passe(libelle_destination="sur le disque de l’application")
        self.assertFalse([chemin for chemin in self.copie.rglob("*") if chemin.is_file()])  # aucun .partiel laissé


class RotationTests(TestCase):
    def test_quotidiennes_et_mensuelles(self):
        dossier = Path(tempfile.mkdtemp(prefix="daplomb-rotation-"))
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        noms = [
            "2026-05-01_0230.dump", "2026-05-15_0230.dump", "2026-06-01_0230.dump", "2026-06-20_0230.dump",
            "2026-07-03_0230.dump", "2026-07-03_1500.dump", "2026-07-04_0230.dump", "2026-07-05_0230.dump",
            "2026-07-05_0230-2.dump", "avant-restauration_2026-07-01_101010.dump", "notes.txt", "2026-07-05_0300.dump.partiel",
        ]
        for nom in noms:
            (dossier / nom).write_bytes(b"x")
        effacees, gardees = rotation(dossier, jours=3, mois=2, proteges={"2026-05-15_0230.dump"})
        self.assertEqual(sorted(effacees), ["2026-05-01_0230.dump", "2026-06-20_0230.dump", "2026-07-05_0230.dump"])
        self.assertEqual(gardees, [])
        self.assertEqual(sorted(p.name for p in dossier.iterdir()), sorted([
            "2026-05-15_0230.dump",  # protégée (dernière vérifiée)
            "2026-06-01_0230.dump", "2026-07-03_0230.dump",  # premières des 2 derniers mois
            "2026-07-03_1500.dump", "2026-07-04_0230.dump", "2026-07-05_0230-2.dump",  # dernières des 3 derniers jours
            "avant-restauration_2026-07-01_101010.dump", "notes.txt",  # hors rotation
        ]))

    def test_quatorze_jours_et_six_mois_par_defaut(self):
        dossier = Path(tempfile.mkdtemp(prefix="daplomb-rotation-"))
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        jour = datetime.date(2026, 1, 1)
        while jour <= datetime.date(2026, 11, 9):
            (dossier / f"{jour:%Y-%m-%d}_0230.dump").write_bytes(b"x")
            jour += datetime.timedelta(days=1)
        rotation(dossier, jours=settings.SAUVEGARDE_JOURS, mois=settings.SAUVEGARDE_MOIS)
        restantes = sorted(p.name for p in dossier.iterdir())
        mensuelles = [f"2026-{mois:02d}-01_0230.dump" for mois in range(6, 12)]
        quotidiennes = [f"2026-10-{j}_0230.dump" for j in range(27, 32)] + [f"2026-11-0{j}_0230.dump" for j in range(1, 10)]
        self.assertEqual(restantes, sorted(set(mensuelles + quotidiennes)))

    def test_seules_les_copies_effacables(self):
        dossier = Path(tempfile.mkdtemp(prefix="daplomb-rotation-"))
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        for nom in ("2026-11-01_0230.dump", "2026-11-02_0230.dump", "2026-11-03_0230.dump", "2026-11-03_0958.dump"):
            (dossier / nom).write_bytes(b"x")
        # Base neuve : elle ne connaît que sa propre copie (2026-11-03_0958) et celle du 2.
        effacees, gardees = rotation(dossier, jours=1, mois=0, effacables={"2026-11-02_0230.dump", "2026-11-03_0958.dump"})
        self.assertEqual(effacees, ["2026-11-02_0230.dump"])
        self.assertEqual(gardees, ["2026-11-01_0230.dump", "2026-11-03_0230.dump"])
        self.assertEqual(sorted(p.name for p in dossier.iterdir()),
                         ["2026-11-01_0230.dump", "2026-11-03_0230.dump", "2026-11-03_0958.dump"])


class AlerteTests(TestCase):
    def test_messages(self):
        maintenant = timezone.now()
        with override_settings(STOCKAGE_SERVEUR=False, DOSSIER_SAUVEGARDES_PC="E:\\Sauvegardes"):
            self.assertIn("Aucune sauvegarde n’a encore réussi", alerte(None, None, maintenant))
            reussie = Sauvegarde.objects.create(statut=StatutSauvegarde.REUSSIE, verifiee=True, debut=maintenant - datetime.timedelta(hours=2),
                                                fin=maintenant - datetime.timedelta(hours=1))
            self.assertEqual(alerte(reussie, reussie, maintenant), "")
            self.assertIn("plus de 36 heures", alerte(reussie, reussie, maintenant + datetime.timedelta(hours=36)))
            echec = Sauvegarde.objects.create(statut=StatutSauvegarde.ECHEC, message="« pg_dump » a échoué : disque plein.", fin=maintenant)
            self.assertIn("a échoué : « pg_dump » a échoué : disque plein.", alerte(echec, reussie, maintenant))
            reussie.verifiee = False
            self.assertIn("n’a pas pu être vérifiée", alerte(reussie, reussie, maintenant))
            reussie.verifiee = True
            reussie.message = f"Base : 2 Mo. Configuration : ATTENTION, {services.CLE_DIFFERENTE} : …"
            self.assertIn("La clé DJANGO_SECRET_KEY de l’application diffère", alerte(reussie, reussie, maintenant))

    def test_echecs_de_nuit_sans_question_d_arret(self):
        """Dernière réussite de plus de 36 heures et échec récent : la cause est l'échec affiché, pas un PC arrêté.
        Si l'échec a lui-même plus de 36 heures, aucune sauvegarde n'a tourné depuis : la question reste posée."""
        maintenant = timezone.now()
        with override_settings(STOCKAGE_SERVEUR=True):
            reussie = Sauvegarde.objects.create(statut=StatutSauvegarde.REUSSIE, verifiee=True,
                                                debut=maintenant - datetime.timedelta(days=3),
                                                fin=maintenant - datetime.timedelta(days=3) + datetime.timedelta(minutes=5))
            echec = Sauvegarde.objects.create(
                statut=StatutSauvegarde.ECHEC, debut=maintenant - datetime.timedelta(hours=10),
                fin=maintenant - datetime.timedelta(hours=10) + datetime.timedelta(minutes=1),
                message="Dossier des sauvegardes : \\\\SERVEUR\\DAplomb\\sauvegardes inaccessible (Host is down).")
            texte = alerte(echec, reussie, maintenant)
            self.assertEqual(texte, f"La dernière sauvegarde (le {services._date(echec.debut)}) a échoué : {echec.message} "
                                    f"La dernière sauvegarde réussie date du {services._date(reussie.fin)}, il y a plus de 36 heures.")
            self.assertNotIn("arrêtés la nuit", texte)
            self.assertEqual(etat()["alerte"], texte)  # même texte par l'API (dernière terminée = l'échec)
            # Échec vieux de 2 jours, rien depuis : le PC ou l'application étaient bien arrêtés.
            echec.debut = maintenant - datetime.timedelta(days=2)
            echec.fin = echec.debut + datetime.timedelta(minutes=1)
            self.assertIn("il y a plus de 36 heures : le PC ou l’application étaient-ils arrêtés la nuit ?",
                          alerte(echec, reussie, maintenant))

    def test_copie_ancienne_restauree(self):
        """Copie de 3 jours restaurée : ni « arrêtés la nuit ? » ni rien tant qu'elle a moins de 36 heures."""
        maintenant = timezone.now()
        with override_settings(STOCKAGE_SERVEUR=False, DOSSIER_SAUVEGARDES_PC="E:\\Sauvegardes"):
            debut = maintenant - datetime.timedelta(days=3)
            restauree = Sauvegarde.objects.create(
                statut=StatutSauvegarde.REUSSIE, verifiee=True, debut=debut, fin=debut,
                message=f"{services.COPIE_RESTAUREE} le 10/11/2026 à 14:05 ; le compte rendu de cette sauvegarde n’est pas dans la copie.")
            texte = alerte(restauree, restauree, maintenant)
            self.assertEqual(texte, f"La base a été restaurée depuis la copie du {services._date(debut)} et aucune sauvegarde n’a "
                                    "réussi depuis : lancez-en une avec le bouton « Sauvegarder maintenant » (compte administrateur) "
                                    "pour protéger ce qui a été saisi depuis la restauration.")
            self.assertNotIn("arrêtés la nuit", texte)
            self.assertEqual(alerte(restauree, restauree, debut + datetime.timedelta(hours=2)), "")

    def test_meme_disque(self):
        for chemin, attendu in (("", True), ("./donnees/sauvegardes", True), ("C:\\Sauvegardes", True), ("c:/sauvegardes", True),
                                ("D:\\Sauvegardes", False), ("\\\\SERVEUR\\DAplomb", False), ('"E:\\Copies"', False)):
            with override_settings(STOCKAGE_SERVEUR=False, DOSSIER_SAUVEGARDES_PC=chemin):
                self.assertEqual(sur_le_meme_disque(), attendu, chemin)
        with override_settings(STOCKAGE_SERVEUR=True, DOSSIER_SAUVEGARDES_PC=""):
            self.assertFalse(sur_le_meme_disque())
        with override_settings(STOCKAGE_SERVEUR=False, DOSSIER_SAUVEGARDES_PC=""):
            self.assertIn("même disque", alerte(None, None, timezone.now()))

    def test_destination_affichee(self):
        with override_settings(STOCKAGE_SERVEUR=False, DOSSIER_SAUVEGARDES_AFFICHE="donnees\\sauvegardes"):
            self.assertEqual(services.destination_affichee(), "donnees\\sauvegardes")
        with override_settings(STOCKAGE_SERVEUR=True, SERVEUR_CHEMIN_AFFICHE="\\\\SERVEUR\\DAplomb\\"):
            self.assertEqual(services.destination_affichee(), "\\\\SERVEUR\\DAplomb\\sauvegardes")
        with override_settings(STOCKAGE_SERVEUR=True, SERVEUR_CHEMIN_AFFICHE="", SERVEUR_ADRESSE="192.168.1.10", SERVEUR_PARTAGE="Donnees/DAplomb"):
            self.assertEqual(services.destination_affichee(), "\\\\192.168.1.10\\Donnees\\DAplomb\\sauvegardes")


class ApiTests(OutilsSimules, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = Utilisateur.objects.create_superuser("admin", "admin@cabinet.fr", "mot-de-passe-solide-42")
        self.moe = Utilisateur.objects.create_user("eco", email="eco@cabinet.fr", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE)
        self.entreprise = Utilisateur.objects.create_user("durand", password="mot-de-passe-solide-42", role=Utilisateur.Role.ENTREPRISE)

    def post(self):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post("/api/sauvegardes", "{}", content_type="application/json")

    def test_droits(self):
        self.assertEqual(self.client.get("/api/sauvegardes/etat").status_code, 401)
        self.assertEqual(self.client.post("/api/sauvegardes").status_code, 401)
        self.client.force_login(self.entreprise)
        self.assertEqual(self.client.get("/api/sauvegardes/etat").status_code, 401)
        self.client.force_login(self.moe)
        reponse = self.client.get("/api/sauvegardes/etat")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(set(reponse.json()), CLES_ETAT)
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(Sauvegarde.objects.count(), 0)

    def test_etat_initial(self):
        self.client.force_login(self.moe)
        donnees = self.client.get("/api/sauvegardes/etat").json()
        self.assertIsNone(donnees["derniere"])
        self.assertIsNone(donnees["derniere_reussie"])
        self.assertFalse(donnees["en_cours"])
        self.assertFalse(donnees["stockage_serveur"])
        self.assertEqual(donnees["destination"], "D:\\Sauvegardes")
        self.assertIn("Aucune sauvegarde", donnees["alerte"])
        self.assertEqual(donnees["heure"], "2 h 30")

    def test_lancer_maintenant(self):
        self.client.force_login(self.admin)
        reponse = self.post()
        self.assertEqual(reponse.status_code, 202, reponse.content)
        self.assertEqual(set(reponse.json()), CLES_ETAT)
        donnees = self.client.get("/api/sauvegardes/etat").json()
        self.assertEqual(donnees["derniere"]["statut"], "REUSSIE", donnees["derniere"]["message"])
        self.assertEqual(donnees["derniere"]["statut_libelle"], "Réussie")
        self.assertTrue(donnees["derniere"]["verifiee"])
        self.assertGreater(donnees["derniere"]["taille"], 0)
        self.assertEqual(set(donnees["derniere"]), {"debut", "fin", "statut", "statut_libelle", "taille", "verifiee", "message"})
        self.assertEqual(set(donnees["derniere_reussie"]), {"fin", "taille", "verifiee"})
        self.assertEqual(donnees["alerte"], "")
        self.assertEqual(Sauvegarde.objects.get().declenchee_par, "admin")

    def test_lancer_pendant_une_sauvegarde_en_cours(self):
        Sauvegarde.objects.create(declenchee_par="planification")
        self.client.force_login(self.admin)
        reponse = self.post()
        self.assertEqual(reponse.status_code, 202)
        self.assertTrue(reponse.json()["en_cours"])
        self.assertEqual(Sauvegarde.objects.count(), 1)

    def test_service_de_taches_injoignable(self):
        self.client.force_login(self.admin)
        with mock.patch("sauvegardes.tasks.sauvegarder.delay", side_effect=ConnectionError("valkey arrêté")):
            self.assertEqual(self.post().status_code, 202)
        sauvegarde = Sauvegarde.objects.get()
        self.assertEqual(sauvegarde.statut, StatutSauvegarde.ECHEC)
        self.assertIn("tâches de fond", sauvegarde.message)


class CommandesTests(OutilsSimules, TestCase):
    def test_sauvegarder(self):
        sortie = StringIO()
        with self.assertNoLogs("sauvegardes", "INFO"):  # compte rendu affiché une seule fois, par la commande
            call_command("sauvegarder", stdout=sortie)
        self.assertIn("Sauvegarde réussie", sortie.getvalue())
        self.assertEqual(sortie.getvalue().count("vérifiée par une restauration d’essai"), 1)
        self.assertEqual(Sauvegarde.objects.get().declenchee_par, "commande")
        self.outils.echecs["pg_dump"] = "pg_dump: error: disque plein"
        sortie = StringIO()
        with self.assertLogs("sauvegardes", "ERROR") as journal, self.assertRaises(CommandError):
            call_command("sauvegarder", stdout=sortie)
        self.assertEqual(sum("disque plein" in ligne for ligne in journal.output), 1)  # une seule fois, par le journal
        self.assertNotIn("disque plein", sortie.getvalue())

    def test_restaurer(self):
        lancer("essai")
        nom = Path(Sauvegarde.objects.get().fichier).name
        self.outils.commandes.clear()
        with self.assertRaises(CommandError):
            call_command("restaurer", "inconnue.dump", "--confirmer", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("restaurer", nom, stdout=StringIO())
        self.assertEqual(self.outils.commandes, [])  # rien sans --confirmer
        Sauvegarde.objects.create(declenchee_par="planification")  # telle qu'elle était dans la copie
        sortie = StringIO()
        with mock.patch("sauvegardes.management.commands.restaurer.call_command") as migrer, \
                mock.patch("sauvegardes.management.commands.restaurer.connections"), override_settings(SECRET_KEY="autre-cle"):
            call_command("restaurer", nom, "--confirmer", stdout=sortie)
        migrer.assert_called_once_with("migrate", interactive=False, verbosity=0)
        self.assertEqual(self.outils.outils(), ["pg_dump", "pg_restore", "psql"])
        self.assertTrue(any(a.startswith("--file=") and "avant-restauration_" in a for a in self.outils.commandes[0]))
        self.assertTrue(list((self.sauvegardes / "base").glob("avant-restauration_*.dump")))
        # 1. La copie est convertie en script SQL, sans toucher la base (une copie abîmée échoue ici).
        conversion = self.outils.commandes[1]
        self.assertEqual(conversion[-1], str(self.sauvegardes / "base" / nom))
        self.assertFalse(any(a.startswith("--dbname") for a in conversion))
        script = next(a.split("=", 1)[1] for a in conversion if a.startswith("--file="))
        # 2. Une seule transaction : tout le schéma public est supprimé (y compris les tables créées par une mise
        #    à jour plus récente que la copie, que migrate recrée ensuite), puis le script est rejoué.
        restauration = self.outils.commandes[2]
        for option in ("-X", "--single-transaction", "ON_ERROR_STOP=1", "--dbname=application_ao"):
            self.assertIn(option, restauration)
        self.assertLess(restauration.index("DROP SCHEMA public CASCADE"), restauration.index("CREATE SCHEMA public"))
        self.assertLess(restauration.index("CREATE SCHEMA public"), restauration.index("-f"))
        self.assertEqual(restauration[restauration.index("-f") + 1], script)
        self.assertEqual(self.outils.scripts_lus, ["CREATE TABLE public.projets_projet (id bigint);\n"])
        self.assertFalse(Path(script).exists())  # script temporaire (toute la base) supprimé
        self.assertIn("DJANGO_SECRET_KEY de l’application diffère", sortie.getvalue())
        self.assertFalse(Sauvegarde.objects.filter(statut=StatutSauvegarde.EN_COURS).exists())

    def test_restaurer_copie_ancienne_alerte(self):
        """Copie de 3 jours restaurée sur le même PC : l'alerte parle de la restauration, pas d'un arrêt la nuit,
        et disparaît à la sauvegarde suivante."""
        lancer("essai")
        nom = Path(Sauvegarde.objects.get().fichier).name
        Sauvegarde.objects.all().delete()  # la base restaurée ne contient que ce qui était dans la copie
        Sauvegarde.objects.create(declenchee_par="planification", debut=timezone.now() - datetime.timedelta(days=3))
        with mock.patch("sauvegardes.management.commands.restaurer.call_command"), \
                mock.patch("sauvegardes.management.commands.restaurer.connections"):
            call_command("restaurer", nom, "--confirmer", stdout=StringIO())
        restauree = Sauvegarde.objects.get()
        self.assertTrue(restauree.message.startswith(services.COPIE_RESTAUREE))
        texte = etat()["alerte"]
        self.assertTrue(texte.startswith("La base a été restaurée depuis la copie du "), texte)
        self.assertIn("« Sauvegarder maintenant »", texte)
        self.assertNotIn("arrêtés la nuit", texte)
        self.assertEqual(lancer("essai").statut, StatutSauvegarde.REUSSIE)
        self.assertEqual(etat()["alerte"], "")

    def test_restaurer_echec_base_inchangee(self):
        lancer("essai")
        nom = Path(Sauvegarde.objects.get().fichier).name
        self.outils.commandes.clear()
        self.outils.echecs["pg_restore"] = "pg_restore: error: could not read from input file: end of file"
        with mock.patch("sauvegardes.management.commands.restaurer.connections"), self.assertRaisesMessage(CommandError, "la base n’a pas été modifiée"):
            call_command("restaurer", nom, "--confirmer", "--sans-copie", stdout=StringIO())
        self.assertEqual(self.outils.outils(), ["pg_restore"])  # copie tronquée : psql n'est jamais lancé
        script = next(a.split("=", 1)[1] for a in self.outils.commandes[0] if a.startswith("--file="))
        self.assertFalse(Path(script).exists())
        self.outils.echecs = {"psql": "psql:/tmp/restauration.sql:12: ERROR: disk full"}
        with mock.patch("sauvegardes.management.commands.restaurer.connections"), \
                self.assertRaisesMessage(CommandError, "la base n’a pas été modifiée : « psql » a échoué : psql:/tmp/restauration.sql:12: ERROR: disk full"):
            call_command("restaurer", nom, "--confirmer", "--sans-copie", stdout=StringIO())

    def test_restaurer_migrate_en_echec(self):
        lancer("essai")
        nom = Path(Sauvegarde.objects.get().fichier).name
        with mock.patch("sauvegardes.management.commands.restaurer.call_command",
                        side_effect=RuntimeError('relation "ged_nouveau" already exists')), \
                mock.patch("sauvegardes.management.commands.restaurer.connections"), self.assertRaises(CommandError) as erreur:
            call_command("restaurer", nom, "--confirmer", stdout=StringIO())
        texte = str(erreur.exception)
        self.assertIn(f"Base restaurée depuis {nom}, mais sa mise à jour de structure (migrate) a échoué", texte)
        self.assertIn('relation "ged_nouveau" already exists', texte)
        self.assertRegex(texte, r"restaurez une autre copie, par exemple avant-restauration_[\d_-]+\.dump")

    def restaurer_avec_fichiers(self, nom: str, sortie: StringIO, **remplacements):
        with mock.patch("sauvegardes.management.commands.restaurer.call_command") as migrer, \
                mock.patch("sauvegardes.management.commands.restaurer.connections"), override_settings(SECRET_KEY="autre-cle"), \
                mock.patch("sauvegardes.miroir.shutil.copyfile", **remplacements):
            try:
                call_command("restaurer", nom, "--confirmer", "--avec-fichiers", stdout=sortie)
            finally:
                migrer.assert_called_once_with("migrate", interactive=False, verbosity=0)

    def test_restaurer_avec_fichiers(self):
        lancer("essai")  # fichiers et archives copiés dans la sauvegarde
        nom = Path(Sauvegarde.objects.get().fichier).name
        shutil.rmtree(self.fichiers / "ged")
        (self.archives / "Chantier.zip").unlink()
        (self.fichiers / "nouveau.pdf").write_bytes(b"%PDF nouveau")  # absent de la sauvegarde : gardé
        sortie = StringIO()
        self.restaurer_avec_fichiers(nom, sortie, wraps=shutil.copyfile)
        self.assertEqual((self.fichiers / "ged" / "3" / "plan.pdf").read_bytes(), b"%PDF plan")
        self.assertEqual((self.archives / "Chantier.zip").read_bytes(), b"PK archive")
        self.assertTrue((self.fichiers / "nouveau.pdf").exists())
        self.assertIn("Fichiers : 1 fichier(s) recopié(s).", sortie.getvalue())
        self.assertIn("Archives : 1 fichier(s) recopié(s).", sortie.getvalue())
        self.assertIn(f"Base restaurée depuis {nom}. Démarrez l’application (docker compose up -d ; sur un nouveau PC : "
                      "installer.ps1)", sortie.getvalue())
        self.assertNotIn("restart", sortie.getvalue())

    def test_restaurer_recopie_des_fichiers_interrompue(self):
        """Base déjà remplacée : code 3 (pas 1, « base inchangée » pour restaurer.ps1), cause et suite expliquées."""
        lancer("essai")
        nom = Path(Sauvegarde.objects.get().fichier).name
        shutil.rmtree(self.fichiers / "ged")
        Sauvegarde.objects.create(declenchee_par="planification")  # telle qu'elle était dans la copie
        sortie = StringIO()
        with self.assertRaises(CommandError) as erreur:
            self.restaurer_avec_fichiers(nom, sortie, side_effect=OSError(errno.ENOSPC, "No space left on device"))
        self.assertEqual(erreur.exception.returncode, 3)
        texte = str(erreur.exception)
        self.assertIn(f"Base restaurée depuis {nom}, mais la recopie des fichiers s’est arrêtée : plus de place sur le "
                      "disque de l’application (0 fichiers copiés). Libérez de la place sur le disque de l’application, "
                      "puis, avant de reprendre le travail, relancez restaurer.ps1 avec la même copie", texte)
        self.assertNotIn("dossier des sauvegardes", texte)
        self.assertIn("DJANGO_SECRET_KEY de l’application diffère", sortie.getvalue())  # affiché avant la recopie
        self.assertFalse(Sauvegarde.objects.filter(statut=StatutSauvegarde.EN_COURS).exists())
        self.assertFalse(list(self.fichiers.rglob("*.partiel")))
        # Fichier illisible ou impossible à écrire : la recopie continue, mais la commande ne se dit pas réussie.
        sortie = StringIO()
        with self.assertRaises(CommandError) as erreur:
            self.restaurer_avec_fichiers(nom, sortie, side_effect=PermissionError(errno.EACCES, "Permission denied"))
        self.assertEqual(erreur.exception.returncode, 3)
        self.assertIn("la recopie des fichiers est incomplète : 1 fichier(s) non recopié(s) (détail ci-dessus). "
                      "Corrigez la cause indiquée, puis", str(erreur.exception))
        self.assertIn("non recopié : ged/3/plan.pdf : Permission denied", sortie.getvalue())
        self.assertNotIn("Base restaurée depuis", sortie.getvalue())


class ReglagesTests(TestCase):
    def test_planification_et_heure(self):
        from config.settings import _heure_sauvegarde

        tache = settings.CELERY_BEAT_SCHEDULE["sauvegarde-nocturne"]
        self.assertEqual(tache["task"], "sauvegardes.tasks.sauvegarder")
        self.assertEqual(tache["schedule"].hour, {settings.SAUVEGARDE_HEURE[0]})
        self.assertEqual(tache["schedule"].minute, {settings.SAUVEGARDE_HEURE[1]})
        self.assertEqual(settings.CELERY_TIMEZONE, "Europe/Paris")
        for texte, attendu in (("2:30", (2, 30)), ("02h45", (2, 45)), ("23", (23, 0)), (" 1 : 05 ", (1, 5)), ("25:00", (2, 30)), ("minuit", (2, 30))):
            self.assertEqual(_heure_sauvegarde(texte), attendu, texte)
