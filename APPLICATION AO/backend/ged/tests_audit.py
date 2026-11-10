"""Audit global : durcissement de la GED (constats 5, 6, 8 à 13, 15 et 16).

- Portail public : aucun corps de requête lu sans session ouverte avec un code (constats 5, 6, 8).
- Pièce cachée et pièce inexistante : même réponse (constat 9) ; pagination bornée (constat 10).
- Purge : adresses IP et navigateurs effacés du journal (constat 11).
- Registres Excel en temps linéaire (constats 12 et 16) ; liste allégée, identique (constat 13).
- Notifications envoyées hors transaction, sans doublon après un arrêt du worker (constat 15).
"""
import datetime
import hashlib
import importlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock, skipUnless

from django.core import mail
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.handlers.wsgi import LimitedStream
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from comptes.models import Utilisateur
from projets.models import LotProjet, Projet

from . import tasks
from .acces import nouveau_code
from .droits import acteur_acces, acteur_cabinet, acteur_intervenant
from .models import (
    Acces,
    AccuseLecture,
    AvisVersion,
    Document,
    EspaceChantier,
    Evenement,
    FichierSource,
    Intervenant,
    Notification,
    Profil,
    ProjetArchive,
    StatutArchive,
    StatutEspace,
    TypeEvenement,
    Version,
    Zone,
)
from .serialisation import document_out, documents_visibles

DOSSIER = tempfile.mkdtemp(prefix="application-ao-audit-ged-")
RACINE_PROJET = Path(__file__).resolve().parents[2]
_compteur = [0]


def reglages_publics():
    """Module config.settings_ged tel que le service « ged » le charge (adresse publique fictive)."""
    import config.settings as base

    sys.modules.pop("config.settings_ged", None)
    with mock.patch.object(base, "GED_URL_PUBLIQUE", "https://ged.cabinet.fr"):
        module = importlib.import_module("config.settings_ged")
    sys.modules.pop("config.settings_ged", None)
    return module


class Lectures:
    """Compte les lectures du corps des requêtes (flux WSGI)."""

    def __enter__(self):
        self.octets = 0
        self.appels = 0
        lire, lire_ligne = LimitedStream.read, LimitedStream.readline

        def read(flux, *args, **kwargs):
            donnees = lire(flux, *args, **kwargs)
            self.appels += 1
            self.octets += len(donnees)
            return donnees

        def readline(flux, *args, **kwargs):
            donnees = lire_ligne(flux, *args, **kwargs)
            self.appels += 1
            self.octets += len(donnees)
            return donnees

        self._patchs = [mock.patch.object(LimitedStream, "read", read), mock.patch.object(LimitedStream, "readline", readline)]
        for patch in self._patchs:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in self._patchs:
            patch.stop()


@override_settings(MEDIA_ROOT=f"{DOSSIER}/fichiers", DOSSIER_ARCHIVES=f"{DOSSIER}/archives", GED_DISQUE_LIBRE_MIN_GO=0, EMAIL_ACTIF=True,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", GED_URL_PUBLIQUE="https://ged.cabinet.fr")
class BaseAudit(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.moe = Utilisateur.objects.create_user("eco", email="eco@cabinet.fr", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE)
        self.projet = Projet.objects.create(nom="Groupe scolaire les Tilleuls", maitre_oeuvre="Atelier A")
        self.lot08 = LotProjet.objects.create(projet=self.projet, code="08", intitule="Menuiseries extérieures", ordre=1)
        self.lot11 = LotProjet.objects.create(projet=self.projet, code="11", intitule="Plâtrerie", ordre=2)
        self.espace = EspaceChantier.objects.create(projet=self.projet, emails_moe="eco@cabinet.fr", lecture_inter_lots=False)
        self.durand, self.code_durand = self.intervenant("Menuiseries Durand", self.lot08, "paul@durand.fr")
        self.martin, self.code_martin = self.intervenant("Plâtrerie Martin", self.lot11, "jean@martin.fr")

    def intervenant(self, nom, lot, email, profil=Profil.ENTREPRISE):
        intervenant = Intervenant.objects.create(espace=self.espace, nom=nom, profil=profil)
        if lot is not None:
            intervenant.lots.add(lot)
        acces = Acces(intervenant=intervenant, nom=nom.split()[-1], email=email)
        code = nouveau_code(acces)
        acces.save()
        return intervenant, code

    def document(self, reference, lot=None, zone=Zone.LOT, categorie="EXE", auteur=None):
        return Document.objects.create(espace=self.espace, zone=zone, lot=lot, categorie=categorie, reference=reference,
                                       titre=f"Plan {reference}", auteur_nom="Durand", auteur_intervenant=auteur)

    def version(self, document, indice="A", **champs):
        _compteur[0] += 1
        contenu = f"%PDF-1.4 plan {_compteur[0]}".encode()
        version = Version(document=document, indice=indice, nom_original="plan.pdf", taille=len(contenu),
                          empreinte=hashlib.sha256(contenu).hexdigest(), deposee_par_nom="Durand", **champs)
        version.fichier.save("plan.pdf", ContentFile(contenu), save=False)
        version.save()
        return version

    def connecter(self, code, client=None) -> Client:
        client = client or Client()
        # Comme le portail : jeton CSRF demandé d'abord, puis renvoyé avec le code.
        jeton = client.get("/api/ged/portail/csrf").json()["csrftoken"]
        reponse = client.post("/api/ged/acces", json.dumps({"code": code}), content_type="application/json", HTTP_X_CSRFTOKEN=jeton)
        self.assertEqual(reponse.status_code, 200, reponse.content)
        return client


# --- Constats 5, 6 et 8 : processus public ------------------------------------------------------------

class PortailSansSessionAuditTests(BaseAudit):
    """Sans session ouverte avec un code, le corps d'un envoi n'est jamais lu (ni par le contrôle CSRF)."""

    ENVOI = {"zone": "LOT", "categorie": "FT"}

    def envoi(self, client, chemin="/api/ged/portail/documents", taille=2 * 1024 * 1024):
        donnees = dict(self.ENVOI, lot_id=self.lot08.pk, fichier=SimpleUploadedFile("plan.pdf", b"%PDF" + b"x" * taille))
        with Lectures() as lectures, self.captureOnCommitCallbacks(execute=True):
            reponse = client.post(chemin, donnees)
        return reponse, lectures

    def verifier(self):
        # Inconnu : refus 401 sans lire le corps (2 Mo annoncés).
        reponse, lectures = self.envoi(Client())
        self.assertEqual((reponse.status_code, reponse.json()), (401, {"detail": "Unauthorized"}))
        self.assertEqual(lectures.octets, 0)
        # Session dont l'accès vient d'être révoqué : même refus, sans lecture.
        client = self.connecter(self.code_durand)
        Acces.objects.filter(intervenant=self.durand).update(actif=False)
        reponse, lectures = self.envoi(client, "/api/ged/portail/versions/1/avis")
        self.assertEqual((reponse.status_code, lectures.octets), (401, 0))
        # Déconnexion sans session : rien à fermer, réponse immédiate.
        reponse, lectures = self.envoi(Client(), "/api/ged/portail/deconnexion")
        self.assertEqual((reponse.status_code, lectures.octets), (204, 0))
        # Session valide : l'envoi est lu et accepté ; sans jeton CSRF, il est refusé (403).
        Acces.objects.filter(intervenant=self.durand).update(actif=True)
        client = self.connecter(self.code_durand)
        reponse, lectures = self.envoi(client, taille=10_000)
        self.assertEqual(reponse.status_code, 201, reponse.content)
        self.assertGreater(lectures.octets, 10_000)
        strict = self.connecter(self.code_durand, Client(enforce_csrf_checks=True))
        self.assertEqual(self.envoi(strict, taille=10)[0].status_code, 403)
        # Préférences (PATCH) et déconnexion avec session : inchangées.
        reponse = client.patch("/api/ged/portail/preferences", json.dumps({"frequence": "QUOTIDIENNE"}), content_type="application/json")
        self.assertEqual(reponse.status_code, 200, reponse.content)
        self.assertEqual(client.post("/api/ged/portail/deconnexion").status_code, 204)
        self.assertEqual(client.get("/api/ged/portail/espace").status_code, 401)

    def test_processus_interne(self):
        self.verifier()

    def test_processus_public(self):
        reglages = reglages_publics()
        self.assertIn("ged.protection.EnvoiSansSessionRefuse", reglages.MIDDLEWARE)
        position = reglages.MIDDLEWARE.index("ged.protection.EnvoiSansSessionRefuse")
        self.assertEqual(reglages.MIDDLEWARE[position - 1], "django.contrib.sessions.middleware.SessionMiddleware")
        with override_settings(ROOT_URLCONF=reglages.ROOT_URLCONF, MIDDLEWARE=reglages.MIDDLEWARE):
            self.verifier()
            # Le refus vient du middleware, avant même Django Ninja (aucune authentification lancée).
            with mock.patch("ged.acces.SessionIntervenant.__call__") as authentification:
                reponse, lectures = self.envoi(Client(), "/api/ged/portail/documents/1/versions")
            self.assertEqual((reponse.status_code, lectures.octets), (401, 0))
            authentification.assert_not_called()
            # Lecture (GET) et saisie du code : jamais bloquées par le middleware.
            self.assertEqual(Client().get("/api/ged/portail/documents").status_code, 401)
            self.connecter(self.code_martin)

    @skipUnless((RACINE_PROJET / "frontend" / "Caddyfile").exists(), "Caddyfile absent (image du backend)")
    def test_caddy_et_gunicorn(self):
        import re

        caddy = (RACINE_PROJET / "frontend" / "Caddyfile").read_text(encoding="utf-8")
        public = caddy[caddy.index("(ged_public)"):]
        self.assertIn("max_size 64KB", public)
        # Saisie du code et déconnexion : corps reçu en entier par Caddy avant d'être transmis.
        bloc = re.search(r"\n\thandle @sans_session \{(.*?)\n\t\}", public, re.S).group(1)
        self.assertIn("request_buffers 16KB", bloc)
        self.assertRegex(public, r"@sans_session path /api/ged/acces /api/ged/portail/deconnexion\n")
        # La déconnexion n'est jamais relayée par le bloc sans tampon, quel que soit l'ordre des blocs.
        portail = re.search(r"\n\t@api_ged \{(.*?)\n\t\}", public, re.S).group(1)
        self.assertIn("not path /api/ged/portail/deconnexion", portail)
        for nom in ("docker-compose.internet.yml", "docker-compose.tunnel.yml"):
            compose = (RACINE_PROJET / nom).read_text(encoding="utf-8")
            self.assertIn('"--threads", "16"', compose, nom)


# --- Constats 9 et 10 : réponses du portail ------------------------------------------------------------

class PortailReponsesAuditTests(BaseAudit):
    def test_piece_cachee_et_piece_inexistante_meme_reponse(self):
        self.verifier_pieces_cachees()

    def test_piece_cachee_et_piece_inexistante_meme_reponse_processus_public(self):
        reglages = reglages_publics()
        with override_settings(ROOT_URLCONF=reglages.ROOT_URLCONF, MIDDLEWARE=reglages.MIDDLEWARE):
            self.verifier_pieces_cachees()

    def verifier_pieces_cachees(self):
        cache_ = self.version(self.document("11-EXE-001", self.lot11))  # autre lot, lecture inter-lots fermée
        source = FichierSource.objects.create(version=cache_, fichier=ContentFile(b"dwg", name="plan.dwg"), nom_original="plan.dwg",
                                              taille=3, empreinte="0" * 64)
        avis = AvisVersion.objects.create(version=cache_, role="BET", avis="VSO", auteur_nom="BET")
        visible = self.version(self.document("08-EXE-001", self.lot08))
        client = self.connecter(self.code_durand)
        self.assertEqual(client.get(f"/api/ged/portail/versions/{visible.pk}/fichier").status_code, 200)
        for cachee, inexistante in (
            (f"/api/ged/portail/versions/{cache_.pk}/fichier", "/api/ged/portail/versions/999999/fichier"),
            (f"/api/ged/portail/versions/{cache_.pk}/fiche", "/api/ged/portail/versions/999999/fiche"),
            (f"/api/ged/portail/sources/{source.pk}", "/api/ged/portail/sources/999999"),
            (f"/api/ged/portail/avis/{avis.pk}/fichier", "/api/ged/portail/avis/999999/fichier"),
        ):
            a, b = client.get(cachee), client.get(inexistante)
            self.assertEqual((a.status_code, a.content), (b.status_code, b.content), cachee)
            self.assertEqual(a.status_code, 404)
            self.assertEqual(a.json()["detail"], "Document introuvable ou plus accessible : rechargez la page.")  # pas « Not Found »
        for cachee, inexistante, donnees in (
            (f"/api/ged/portail/versions/{cache_.pk}/lecture", "/api/ged/portail/versions/999999/lecture", {}),
            (f"/api/ged/portail/versions/{cache_.pk}/avis", "/api/ged/portail/versions/999999/avis", {"avis": "VSO"}),
            (f"/api/ged/portail/documents/{cache_.document.pk}/versions", "/api/ged/portail/documents/999999/versions",
             {"indice": "B", "fichier": SimpleUploadedFile("plan.pdf", b"%PDF-1.4 plan")}),
        ):
            a = client.post(cachee, dict(donnees))
            if "fichier" in donnees:
                donnees["fichier"].seek(0)
            b = client.post(inexistante, dict(donnees))
            self.assertEqual((a.status_code, a.content), (b.status_code, b.content), cachee)
            self.assertEqual(a.status_code, 404, a.content)
            self.assertNotIn(b"Not Found", a.content)

    def test_numero_de_page_enorme(self):
        self.version(self.document("08-EXE-001", self.lot08))
        Evenement.objects.create(espace=self.espace, type=TypeEvenement.DEPOT, acteur="Durand", description="Plan",
                                 document=Document.objects.get())
        client = self.connecter(self.code_durand)
        for page in ("1844674407370955170", "99999999999999999999999", "-5"):
            reponse = client.get("/api/ged/portail/journal", {"page": page})
            self.assertEqual(reponse.status_code, 200, page)
        self.assertEqual(client.get("/api/ged/portail/journal", {"page": "-5"}).json()["resultats"][0]["description"], "Plan")


# --- Constat 11 : purge ----------------------------------------------------------------------------------

class PurgeAuditTests(BaseAudit):
    def test_purge_efface_adresses_ip_et_navigateurs(self):
        from .archivage import purger

        self.version(self.document("08-EXE-001", self.lot08), deposee_le=timezone.now() - datetime.timedelta(days=2))
        Evenement.objects.create(espace=self.espace, type=TypeEvenement.CONNEXION, acteur="Paul (Menuiseries Durand)", description="Connexion",
                                 adresse_ip="203.0.113.7", navigateur="Mozilla/5.0 (Linux; Android 14)")
        archive = ProjetArchive.objects.create(projet=self.projet, nom_projet=self.projet.nom, statut=StatutArchive.VERIFIEE,
                                               nom_fichier="Archive.zip", telechargee_le=timezone.now())
        ProjetArchive.objects.filter(pk=archive.pk).update(cree_le=timezone.now() - datetime.timedelta(days=1))
        archive.refresh_from_db()
        Path(DOSSIER, "archives").mkdir(parents=True, exist_ok=True)
        Path(DOSSIER, "archives", "Archive.zip").write_bytes(b"PK")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertGreater(purger(archive), 0)
        evenement = Evenement.objects.get(type=TypeEvenement.CONNEXION)
        self.assertEqual((evenement.adresse_ip, evenement.navigateur), (None, ""))
        self.assertEqual(evenement.acteur, "Paul (Menuiseries Durand)")  # le journal garde qui et quand
        self.assertEqual(EspaceChantier.objects.get().statut, StatutEspace.CLOS)


# --- Constats 12 et 16 : registres Excel ----------------------------------------------------------------

class Compteur:
    """Compte les lectures de Worksheet.max_row et max_column (chacune parcourt toutes les cellules)."""

    def __enter__(self):
        from openpyxl.worksheet.worksheet import Worksheet

        self.appels = 0
        self._patchs = []
        for nom in ("max_row", "max_column"):
            original = getattr(Worksheet, nom)

            def lire(feuille, _original=original):
                self.appels += 1
                return _original.fget(feuille)

            self._patchs.append(mock.patch.object(Worksheet, nom, property(lire)))
        for patch in self._patchs:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in self._patchs:
            patch.stop()


class RegistresAuditTests(BaseAudit):
    def remplir(self, nombre):
        for n in range(nombre):
            document = self.document(f"08-EXE-{n:03d}", self.lot08)
            self.version(document, "A", deposee_le=timezone.now() - datetime.timedelta(days=2))
            self.version(document, "B", objet="=HYPERLINK(\"http://exemple.invalid\")")

    def test_registre_du_portail_et_du_cabinet_lineaire(self):
        from openpyxl import load_workbook

        from .vues import registre_xlsx

        cabinet = acteur_cabinet(self.moe)
        appels = []
        for nombre in (3, 30):
            Document.objects.all().delete()
            self.remplir(nombre)
            with Compteur() as compteur:
                reponse = registre_xlsx(self.espace, cabinet)
            appels.append(compteur.appels)
        self.assertEqual(appels[0], appels[1])  # indépendant du nombre de lignes : plus de parcours par ligne
        feuille = load_workbook(io.BytesIO(reponse.content)).active
        self.assertEqual(feuille.max_row, 3 + 60)
        derniere = [c for c in feuille[4]]
        self.assertEqual(derniere[6].value, "B")
        self.assertTrue(derniere[0].font.b)  # indice en vigueur en gras
        self.assertFalse(feuille[5][0].font.b)  # indice remplacé
        self.assertEqual(derniere[9].data_type, "s")  # « =… » saisi : texte, jamais une formule
        self.assertTrue(str(derniere[9].value).startswith("=HYPERLINK"))

    def test_registre_de_l_archive_lineaire(self):
        from openpyxl import load_workbook

        from .archivage import Entree, _registre_xlsx

        appels = []
        for nombre in (3, 30):
            Document.objects.all().delete()
            self.remplir(nombre)
            registre = [
                {"document": v.document, "version": v, "statut": "EN_VIGUEUR" if v.indice == "B" else "REMPLACEE",
                 "entree": Entree(f"Lot 08/EXE/{v.document.reference}_{v.indice}.pdf") if v.indice == "B" else None}
                for v in Version.objects.select_related("document__lot").order_by("document__reference", "-indice")
            ]
            with Compteur() as compteur:
                contenu = _registre_xlsx(self.projet, registre)
            appels.append(compteur.appels)
        self.assertEqual(appels[0], appels[1])
        feuille = load_workbook(io.BytesIO(contenu)).active
        self.assertEqual(feuille.max_row, 3 + 60)
        self.assertEqual(feuille.cell(4, 15).hyperlink.target, "../Lot 08/EXE/08-EXE-000_B.pdf")
        self.assertEqual(feuille.cell(5, 15).value, "(fichier absent)")
        self.assertEqual(feuille.cell(4, 10).data_type, "s")


# --- Constat 13 : liste des documents ---------------------------------------------------------------------

class ListeAuditTests(BaseAudit):
    def remplir(self, nombre):
        bet, _ = self.intervenant("BET Fluides", None, "bet@fluides.fr", Profil.MOE_EXTERNE)
        for n in range(nombre):
            lot, categorie = (self.lot08, "OS") if n % 3 == 0 else ((self.lot11, "EXE") if n % 3 == 1 else (None, "CR"))
            document = self.document(f"D-{n:03d}", lot, Zone.LOT if lot else Zone.COMMUN, categorie, auteur=self.durand)
            ancien = self.version(document, "A", deposee_le=timezone.now() - datetime.timedelta(days=3), diffusion="VISA", visa="VAO",
                                  vise_le=timezone.now() - datetime.timedelta(days=2))
            recent = self.version(document, "B", diffusion="VISA", visa="EN_ATTENTE", echeance_visa=timezone.localdate())
            AvisVersion.objects.create(version=ancien, role="BET", avis="VAO", observations="Reprendre", auteur_nom="BET", intervenant=bet)
            AvisVersion.objects.create(version=recent, role="CT", avis="SUSPENDU", auteur_nom="CT")
            FichierSource.objects.create(version=recent, fichier=ContentFile(b"dwg", name="p.dwg"), nom_original="p.dwg", taille=3, empreinte="0" * 64)
            for intervenant in (self.durand, self.martin):
                AccuseLecture.objects.create(version=ancien, intervenant=intervenant, nom_declare=intervenant.nom)

    def acteurs(self):
        bet = Acces.objects.select_related("intervenant").get(email="bet@fluides.fr")
        durand = Acces.objects.select_related("intervenant").get(intervenant=self.durand)
        martin = Acces.objects.select_related("intervenant").get(intervenant=self.martin)
        return {"cabinet": acteur_cabinet(self.moe), "durand": acteur_acces(durand), "martin": acteur_acces(martin),
                "bet": acteur_acces(bet), "lecture": acteur_intervenant(self.martin)}

    def test_liste_identique_a_la_fiche_complete(self):
        from .vues import lister

        self.remplir(12)
        for nom, acteur in self.acteurs().items():
            attendu = [document_out(d, acteur) for d in documents_visibles(self.espace, acteur)]  # ancienne méthode
            obtenu = lister(self.espace, acteur)
            self.assertEqual(json.dumps(obtenu, default=str, sort_keys=True), json.dumps(attendu, default=str, sort_keys=True), nom)
            self.assertTrue(obtenu, nom)

    def test_nombre_de_requetes_constant(self):
        from .vues import lister

        self.remplir(3)
        acteurs = self.acteurs()
        for nom in ("cabinet", "durand"):
            acteur = acteurs[nom]
            acteur.lots()
            with self.assertNumQueries(5):
                lister(self.espace, acteur)
        self.remplir_suite = self.remplir  # même nombre de requêtes avec 4 fois plus de documents
        Document.objects.all().delete()
        Acces.objects.filter(email="bet@fluides.fr").delete()
        Intervenant.objects.filter(nom="BET Fluides").delete()
        self.remplir(12)
        with self.assertNumQueries(5):
            lister(self.espace, acteurs["cabinet"])


# --- Constat 15 : notifications ---------------------------------------------------------------------------

class Arret(BaseException):
    """Arrêt brutal du worker en plein envoi (docker compose stop, PC éteint)."""


class NotificationsAuditTests(BaseAudit):
    def evenements(self):
        document = self.document("COM-CR-001", None, Zone.COMMUN, "CR")
        version = self.version(document)
        return Evenement.objects.create(espace=self.espace, type=TypeEvenement.DEPOT, acteur="Cabinet", description="Compte rendu",
                                        document=document, version=version, a_notifier=True,
                                        date=timezone.now() - datetime.timedelta(minutes=20))

    def test_envoi_hors_transaction(self):
        for n in range(25):
            self.intervenant(f"Entreprise {n}", self.lot08, f"contact{n}@entreprise.fr")
        evenement = self.evenements()
        niveau = len(connection.atomic_blocks)
        pauses = []
        with override_settings(TESTS=False), mock.patch("time.sleep", side_effect=lambda _s: pauses.append(len(connection.atomic_blocks))):
            tasks.notifier_espace(self.espace.pk)
        self.assertEqual(pauses, [niveau])  # une pause (27 courriels), sans transaction ouverte par la tâche
        self.assertEqual(len(mail.outbox), 27)
        evenement.refresh_from_db()
        self.assertFalse(evenement.a_notifier)
        self.assertIsNotNone(evenement.notifie_le)

    def test_pas_de_doublon_apres_un_arret_en_plein_envoi(self):
        evenement = self.evenements()
        partis = []

        class Connexion:
            def __init__(self, arret_apres):
                self.arret_apres = arret_apres

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def send_messages(self, messages):
                if self.arret_apres is not None and len(partis) >= self.arret_apres:
                    raise Arret
                partis.extend(m.to[0] for m in messages)
                return len(messages)

        with mock.patch("ged.notifications.get_connection", return_value=Connexion(arret_apres=1)), self.assertRaises(Arret):
            tasks.notifier_espace(self.espace.pk)
        self.assertEqual(len(partis), 1)
        evenement.refresh_from_db()
        self.assertTrue(evenement.a_notifier)  # repris par la relance
        self.assertTrue(cache.add(f"ged:notifications:{self.espace.pk}", 1, 1))  # verrou libéré
        cache.delete(f"ged:notifications:{self.espace.pk}")
        with mock.patch("ged.notifications.get_connection", return_value=Connexion(arret_apres=None)):
            tasks.notifier_espace(self.espace.pk)
        # Chacun une seule fois. Compte rendu pour information : la maîtrise d'œuvre l'aura dans le
        # récapitulatif du matin (seul ce qui est à viser lui part tout de suite).
        self.assertEqual(sorted(partis), ["jean@martin.fr", "paul@durand.fr"])
        evenement.refresh_from_db()
        self.assertFalse(evenement.a_notifier)

    def test_un_seul_envoi_a_la_fois_par_espace(self):
        self.evenements()
        cache.add(f"ged:notifications:{self.espace.pk}", 1, 60)
        tasks.notifier_espace(self.espace.pk)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Evenement.objects.get().a_notifier)
        cache.delete(f"ged:notifications:{self.espace.pk}")
        tasks.notifier_espace(self.espace.pk)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["jean@martin.fr", "paul@durand.fr"])
        self.assertEqual(Notification.objects.filter(envoyee_le__isnull=False).count(), 2)
        self.assertFalse(Evenement.objects.get().a_notifier)
