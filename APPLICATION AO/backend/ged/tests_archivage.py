import io
import json
import shutil
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from comptes.models import Utilisateur
from entreprises.models import Entreprise
from offres.models import LigneOffre, Offre
from projets.models import GenrePoste, LotProjet, Poste, Projet
from referentiel.models import Lot

from .models import EspaceChantier, ProjetArchive, Version

DOSSIER = tempfile.mkdtemp(prefix="application-ao-archives-")


@override_settings(MEDIA_ROOT=f"{DOSSIER}/fichiers", DOSSIER_ARCHIVES=f"{DOSSIER}/archives", GED_DISQUE_LIBRE_MIN_GO=0, EMAIL_ACTIF=False)
class ArchivageTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER, ignore_errors=True)

    def setUp(self):
        self.moe = Utilisateur.objects.create_user("eco", email="eco@cabinet.fr", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE)
        self.client.force_login(self.moe)
        self.projet = Projet.objects.create(nom="Groupe scolaire : les Tilleuls / phase 2", maitre_oeuvre="Atelier A")
        self.lot = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="08"), code="08", intitule="Menuiseries extérieures et occultations", ordre=1)
        Poste.objects.create(lot=self.lot, ordre=10, genre=GenrePoste.CHAPITRE, titre="Menuiseries")
        Poste.objects.create(lot=self.lot, ordre=20, titre="Fenêtre", unite="u", quantite=Decimal("10"), prix_unitaire=Decimal("800"))
        entreprise = Entreprise.objects.create(raison_sociale="Menuiseries Durand")
        self.offre = Offre(projet=self.projet, lot=self.lot, entreprise=entreprise, montant_base=Decimal("8000"), nom_original="offre.pdf")
        self.offre.fichier.save("offre.pdf", SimpleUploadedFile("offre.pdf", b"%PDF offre"), save=False)
        self.offre.save()
        LigneOffre.objects.create(offre=self.offre, ordre=1, designation="Fenêtre", quantite=Decimal("10"), prix_unitaire=Decimal("800"), montant=Decimal("8000"))

    def json(self, methode, url, donnees=None, attendu=200):
        with self.captureOnCommitCallbacks(execute=True):
            reponse = getattr(self.client, methode)(url, json.dumps(donnees or {}), content_type="application/json") if methode != "get" else self.client.get(url)
        self.assertEqual(reponse.status_code, attendu, reponse.content)
        return reponse.json() if reponse.content and reponse.get("Content-Type", "").startswith("application/json") else None

    def test_archive_verifiee_puis_purge_des_fichiers(self):
        self.json("post", f"/api/projets/{self.projet.pk}/ged", {}, attendu=201)
        espace = EspaceChantier.objects.get()
        url = f"/api/ged/espaces/{espace.pk}"
        titre_long = "Plan de calepinage des menuiseries de la façade nord du bâtiment A, niveaux R+1 à R+3"
        with self.captureOnCommitCallbacks(execute=True):
            plan = self.client.post(f"{url}/documents", {"fichier": SimpleUploadedFile("plan.pdf", b"%PDF plan A"), "zone": "LOT", "lot_id": self.lot.pk,
                                                         "categorie": "EXE", "titre": titre_long, "diffusion": "VISA"}).json()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"{url}/versions/{plan['versions'][0]['id']}/visa", {"statut": "VAO", "commentaire": "Fixations à préciser."})
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"{url}/documents/{plan['id']}/versions", {"fichier": SimpleUploadedFile("plan B.pdf", b"%PDF plan B"), "sources": [SimpleUploadedFile("plan B.dwg", b"AC1032")]})
        self.json("patch", url, {"date_reception": "2027-06-30"})

        etat = self.json("get", f"/api/projets/{self.projet.pk}/archives")
        self.assertGreater(etat["bilan"]["octets"], 0)
        self.assertEqual(etat["bilan"]["prix_recus"], 1)
        archive = self.json("post", f"/api/projets/{self.projet.pk}/archives", attendu=201)
        archive = self.json("get", f"/api/projets/{self.projet.pk}/archives")["archives"][0]
        self.assertEqual(archive["statut"], "VERIFIEE", archive["message"])
        self.assertEqual(archive["conserver_jusqu_au"], "2037-06-30")
        chemin = Path(DOSSIER) / "archives" / archive["nom_fichier"]
        with zipfile.ZipFile(chemin) as zip_archive:
            noms = zip_archive.namelist()
            racine = len(f"{chemin.stem}/")
            self.assertTrue(all(racine + len(n) <= 150 for n in noms), max(noms, key=len))
            self.assertIn("Lisez-moi.txt", noms)
            self.assertTrue(any(n.startswith("01 Pieces ecrites/") and n.endswith("CCTP lot 08.pdf") for n in noms))
            self.assertTrue(any(n.startswith("03 Offres/Lot 08") and n.endswith("offre.pdf") for n in noms))
            self.assertIn("03 Offres/Rapport d'analyse des offres (ACT).pdf", noms)
            ged = [n for n in noms if n.startswith("04 GED/Lot 08")]
            # B en examen et A (visé VAO, toujours à utiliser) à la racine de la catégorie.
            self.assertTrue(any("/EXE/08-EXE-001_B_" in n and n.endswith(".pdf") for n in ged), ged)
            self.assertTrue(any("/EXE/08-EXE-001_A_VAO_" in n for n in ged), ged)
            self.assertTrue(any(n.endswith("fiche de visa.pdf") for n in ged), ged)
            self.assertTrue(any(n.endswith(".dwg") for n in ged), ged)
            journal = zip_archive.read("04 GED/Journal.csv").decode("utf-8-sig")
            self.assertNotIn("127.0.0.1", journal)
            self.assertIn("Visa avec observations", journal)
            self.assertIn("2037", zip_archive.read("Lisez-moi.txt").decode())

        # Purge : refusée tant que l'archive n'a été ni téléchargée ni copiée.
        self.json("post", f"/api/archives/{archive['id']}/purge", {}, attendu=400)
        reponse = self.client.get(f"/api/archives/{archive['id']}/telecharger")
        self.assertEqual((reponse.status_code, reponse["Content-Type"]), (200, "application/zip"))
        b"".join(reponse.streaming_content)
        programmee = self.json("post", f"/api/archives/{archive['id']}/purge", {})
        self.assertIsNotNone(programmee["purge_prevue_le"])
        self.json("post", f"/api/archives/{archive['id']}/purge", {"maintenant": True}, attendu=403)  # réservé à l'administrateur
        # Échéance atteinte : la tâche planifiée purge les fichiers, pas les données.
        from .archivage import purges_programmees

        ProjetArchive.objects.update(purge_prevue_le=timezone.now())
        fichier_offre = Path(self.offre.fichier.path)
        version = Version.objects.filter(document_id=plan["id"]).order_by("deposee_le").first()
        fichier_plan = Path(version.fichier.path)
        with self.captureOnCommitCallbacks(execute=True):
            purges_programmees()
        self.assertFalse(fichier_offre.exists() or fichier_plan.exists())
        self.assertEqual(LigneOffre.objects.filter(offre__projet=self.projet).count(), 1)  # les prix reçus restent
        self.assertEqual(Offre.objects.get().montant_base, Decimal("8000.00"))
        self.assertEqual(EspaceChantier.objects.get().statut, "CLOS")
        documents = self.json("get", f"{url}/documents")
        self.assertTrue(documents[0]["versions"][0]["fichier_archive"])
        self.assertGreater(ProjetArchive.objects.get().octets_liberes, 0)
        # L'archive des fichiers purgés ne peut pas être supprimée par erreur.
        self.json("delete", f"/api/archives/{archive['id']}", attendu=409)

    def test_suppression_totale_reservee_a_l_administrateur(self):
        bilan = self.json("get", f"/api/projets/{self.projet.pk}/bilan")
        self.assertEqual((bilan["offres"], bilan["prix_recus"]), (1, 1))
        self.json("delete", f"/api/projets/{self.projet.pk}", attendu=403)
        admin = Utilisateur.objects.create_user("admin", password="mot-de-passe-solide-42", role=Utilisateur.Role.ADMINISTRATEUR)
        self.client.force_login(admin)
        self.json("delete", f"/api/projets/{self.projet.pk}", attendu=204)
        _ = io  # noqa: F841
