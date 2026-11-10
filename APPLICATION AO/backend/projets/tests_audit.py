"""Audit global (constat 3) : un lot qui a une vie sur le chantier ne s'efface pas d'un clic."""
import shutil
import tempfile

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from comptes.models import Utilisateur
from entreprises.models import Entreprise

from .models import LotProjet, Projet

DOSSIER_TEST = tempfile.mkdtemp(prefix="application-ao-audit-lots-")


@override_settings(MEDIA_ROOT=DOSSIER_TEST)
class SuppressionLotAuditTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        self.moe = Utilisateur.objects.create_user("moe", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE)
        self.admin = Utilisateur.objects.create_user("admin", password="mot-de-passe-solide-42", role=Utilisateur.Role.ADMINISTRATEUR)
        self.projet = Projet.objects.create(nom="Groupe scolaire des Tilleuls")
        self.lot = LotProjet.objects.create(projet=self.projet, code="08", intitule="Menuiseries extérieures", ordre=0)

    def supprimer(self, utilisateur, attendu):
        self.client.force_login(utilisateur)
        reponse = self.client.delete(f"/api/lots-projet/{self.lot.pk}")
        self.assertEqual(reponse.status_code, attendu, reponse.content)
        return reponse

    def test_lot_en_redaction_supprime_par_la_moe(self):
        self.supprimer(self.moe, 204)
        self.assertFalse(LotProjet.objects.filter(pk=self.lot.pk).exists())

    def test_lot_avec_documents_ged_jamais_supprime(self):
        from ged.models import Document, EspaceChantier, Version, Zone

        espace = EspaceChantier.objects.create(projet=self.projet)
        document = Document.objects.create(espace=espace, zone=Zone.LOT, lot=self.lot, categorie="EXE", reference="08-EXE-001",
                                           titre="Façade nord", auteur_nom="Durand")
        version = Version(document=document, indice="A", nom_original="plan.pdf", taille=4, empreinte="0" * 64, deposee_par_nom="Durand")
        version.fichier.save("plan.pdf", ContentFile(b"%PDF"), save=False)
        version.save()
        for utilisateur in (self.moe, self.admin):
            reponse = self.supprimer(utilisateur, 409)
            self.assertIn("jamais supprimés", reponse.json()["detail"])
        self.assertTrue(Document.objects.filter(pk=document.pk).exists())
        self.assertTrue(version.fichier.storage.exists(version.fichier.name))

    def test_lot_avec_offres_reserve_a_l_administrateur(self):
        from offres.models import Offre

        entreprise = Entreprise.objects.create(raison_sociale="Menuiseries Durand")
        Offre.objects.create(projet=self.projet, lot=self.lot, entreprise=entreprise)
        reponse = self.supprimer(self.moe, 403)
        self.assertIn("réservée à l’administrateur", reponse.json()["detail"])
        self.assertEqual(Offre.objects.count(), 1)
        self.supprimer(self.admin, 204)
        self.assertEqual(Offre.objects.count(), 0)

    def test_lot_avec_consultations_reserve_a_l_administrateur(self):
        from dce.models import ConsultationEntreprise

        entreprise = Entreprise.objects.create(raison_sociale="Menuiseries Durand")
        ConsultationEntreprise.objects.create(projet=self.projet, lot=self.lot, entreprise=entreprise)
        self.supprimer(self.moe, 403)
        self.assertTrue(ConsultationEntreprise.objects.exists())
