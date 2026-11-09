import io
import json
import shutil
import tempfile
import zipfile
from decimal import Decimal

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from comptes.models import Utilisateur
from entreprises.models import Contact, Entreprise
from projets import pieces
from projets.models import GenrePoste, LotProjet, Poste, Projet, TypePiece
from referentiel.models import Lot

from .models import ConsultationEntreprise, DossierDCE, Envoi

DOSSIER_TEST = tempfile.mkdtemp(prefix="application-ao-dce-")
MODELE = {"nom": "Modèle d'essai", "clauses": [{"genre": "CHAPITRE", "titre": "Objet", "contenu": "<p>Opération {{nom_operation}}.</p>"}]}


@override_settings(MEDIA_ROOT=DOSSIER_TEST)
class DceTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        self.utilisateur = Utilisateur.objects.create_user("eco", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE)
        self.client.force_login(self.utilisateur)
        self.projet = Projet.objects.create(nom="Groupe scolaire : les Tilleuls", maitre_ouvrage="Ville de Saint-Aubin", maitre_oeuvre="Atelier A", type_marche="PRIVE")
        self.lot08 = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="08"), code="08", intitule="Menuiseries extérieures", ordre=1)
        self.lot11 = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="11"), code="11", intitule="Plâtrerie / Cloisons", ordre=2)
        for lot in (self.lot08, self.lot11):
            Poste.objects.create(lot=lot, ordre=10, genre=GenrePoste.CHAPITRE, titre="Ouvrages")
            Poste.objects.create(lot=lot, ordre=20, genre=GenrePoste.OUVRAGE, titre="Ouvrage", unite="u", quantite=Decimal("2"))
        pieces.creer_piece(self.projet, TypePiece.RC, modele=MODELE)
        pieces.creer_piece(self.projet, TypePiece.CCAP, modele=MODELE)
        pieces.creer_piece(self.projet, TypePiece.AE, self.lot08, modele=MODELE)
        self.durand = Entreprise.objects.create(raison_sociale="Menuiseries Durand", email="contact@durand.fr")
        self.durand.lots.add(Lot.objects.get(code="08"))
        self.martin = Entreprise.objects.create(raison_sociale="Plâtrerie Martin")
        self.martin.lots.add(Lot.objects.get(code="11"))
        Contact.objects.create(entreprise=self.martin, nom="Lise Martin", email="lise@martin.fr", principal=True)

    def json(self, methode, url, donnees=None, attendu=200):
        if methode == "get":
            reponse = self.client.get(url, donnees or {})
        else:
            # Les tâches de fond sont lancées après validation de la transaction.
            with self.captureOnCommitCallbacks(execute=True):
                reponse = getattr(self.client, methode)(url, json.dumps(donnees or {}), content_type="application/json")
        self.assertEqual(reponse.status_code, attendu, reponse.content)
        return reponse.json() if reponse.content else None

    def joindre(self, nom, contenu=b"%PDF-1.4 plan", **champs):
        return self.client.post(f"/api/projets/{self.projet.pk}/dce/pieces-jointes", {"fichier": SimpleUploadedFile(nom, contenu), **champs})

    def zip(self, dossier_id):
        reponse = self.client.get(f"/api/dce/dossiers/{dossier_id}/telecharger")
        self.assertEqual(reponse.status_code, 200)
        return zipfile.ZipFile(io.BytesIO(b"".join(reponse.streaming_content)))

    def test_controle(self):
        controle = self.json("get", f"/api/projets/{self.projet.pk}/dce")["controle"]
        textes = [p["texte"] for p in controle]
        self.assertIn("Lot 11 – Plâtrerie / Cloisons : acte d'engagement non rédigé.", textes)
        self.assertIn("Aucun plan joint au DCE.", textes)
        self.assertTrue(any(p["niveau"] == "OK" and p["texte"].startswith("Lot 08") for p in controle))
        self.assertIn("Date limite de remise des offres non renseignée.", textes)

    def test_dce_complet_arborescence(self):
        self.assertEqual(self.joindre("Plan RDC.pdf", categorie="PLANS").status_code, 201)
        self.assertEqual(self.joindre("Plan menuiseries.pdf", categorie="PLANS", lot_id=self.lot08.pk, titre="Carnet de détails").status_code, 201)
        self.assertEqual(self.joindre("Amiante.pdf", categorie="DIAGNOSTICS").status_code, 201)
        self.assertEqual(self.joindre("virus.exe").status_code, 400)

        apercu = self.json("get", f"/api/projets/{self.projet.pk}/dce/apercu", {"indice": "B"})
        self.assertEqual(apercu["racine"], "DCE Groupe scolaire - les Tilleuls - Indice B.zip")

        dossier = self.json("post", f"/api/projets/{self.projet.pk}/dce/dossiers", {"indice": "B", "avec_word": False}, attendu=202)
        dossier = self.json("get", f"/api/projets/{self.projet.pk}/dce")["dossiers"][0]
        self.assertEqual(dossier["statut"], "PRET", dossier["message"])
        noms = self.zip(dossier["id"]).namelist()
        racine = ""  # pas de dossier racine : « Extraire tout » en crée un au nom du .zip
        self.assertEqual(noms[0], "00 - Bordereau des pièces.pdf")
        self.projet.refresh_from_db()
        self.assertEqual(self.projet.indice, "B")  # toutes les pièces portent l'indice du DCE
        attendus = [
            "01 - Pièces administratives/RC - Règlement de la consultation.pdf",
            "01 - Pièces administratives/CCAP - Cahier des clauses administratives particulières.pdf",
            "01 - Pièces administratives/Actes d'engagement/AE lot 08 - Menuiseries extérieures.pdf",
            "01 - Pièces administratives/Actes d'engagement/AE lot 08 - Menuiseries extérieures.docx",
            "02 - Pièces techniques/Lot 08 - Menuiseries extérieures/CCTP lot 08.pdf",
            "02 - Pièces techniques/Lot 08 - Menuiseries extérieures/DPGF lot 08 (à compléter).xlsx",
            "02 - Pièces techniques/Lot 08 - Menuiseries extérieures/Plans du lot/Carnet de détails.pdf",
            "02 - Pièces techniques/Lot 11 - Plâtrerie - Cloisons/CCTP lot 11.pdf",
            "03 - Plans/Plan RDC.pdf",
            "05 - Diagnostics/Amiante.pdf",
        ]
        for chemin in attendus:
            self.assertIn(racine + chemin, noms)
        self.assertNotIn(racine + "01 - Pièces administratives/CCAP - Cahier des clauses administratives particulières.docx", noms)
        self.assertTrue(all(len(n) <= 140 for n in noms))

        import pdfplumber

        archive = self.zip(dossier["id"])
        with pdfplumber.open(io.BytesIO(archive.read(noms[0]))) as pdf:
            texte = "\n".join(p.extract_text() or "" for p in pdf.pages)
        self.assertIn("Bordereau des pièces du DCE", texte)
        self.assertIn("Carnet de détails", texte)

    def test_consultation_privee_par_courriel(self):
        suggestions = self.json("get", f"/api/projets/{self.projet.pk}/dce/suggestions", {"lot_id": self.lot08.pk})
        self.assertEqual([s["raison_sociale"] for s in suggestions], ["Menuiseries Durand"])
        self.json("post", f"/api/projets/{self.projet.pk}/dce/consultations", {"lot_id": self.lot08.pk, "entreprise_ids": [self.durand.pk]}, attendu=201)
        self.json("post", f"/api/projets/{self.projet.pk}/dce/consultations", {"lot_id": self.lot11.pk, "entreprise_ids": [self.martin.pk]}, attendu=201)
        modeles = self.json("get", f"/api/projets/{self.projet.pk}/dce/messages")

        with override_settings(EMAIL_ACTIF=True):
            envois = self.json(
                "post", f"/api/projets/{self.projet.pk}/dce/envois/entreprises",
                {"entreprise_ids": [self.durand.pk, self.martin.pk], **modeles["entreprise"], "indice": "A"}, attendu=202,
            )
        self.assertEqual(len(envois), 2)
        self.assertEqual(len(mail.outbox), 2)
        courriel = next(m for m in mail.outbox if m.to == ["contact@durand.fr"])
        self.assertIn("Menuiseries Durand", courriel.body)
        self.assertTrue(courriel.subject.endswith("– lot 08"))
        self.assertIn("lot 08 Menuiseries extérieures", courriel.body)
        nom, contenu, _ = courriel.attachments[0]
        self.assertTrue(nom.endswith("Menuiseries Durand.zip"))
        noms = zipfile.ZipFile(io.BytesIO(contenu)).namelist()
        self.assertTrue(any(n.endswith("00 - Lettre de consultation.pdf") for n in noms))
        self.assertTrue(any("Lot 08" in n for n in noms))
        self.assertFalse(any("Lot 11" in n for n in noms))  # seulement les lots de l'entreprise
        self.assertEqual(next(m for m in mail.outbox if m.to != ["contact@durand.fr"]).to, ["lise@martin.fr"])

        consultation = ConsultationEntreprise.objects.get(entreprise=self.durand)
        self.assertEqual(consultation.statut, "CONSULTEE")
        self.assertIsNotNone(consultation.consultee_le)
        historique = self.json("get", f"/api/entreprises/{self.durand.pk}")["historique"]
        self.assertEqual(historique[0]["statut_libelle"], "Consultée")
        self.json("delete", f"/api/dce/consultations/{consultation.pk}", attendu=409)
        self.json("patch", f"/api/dce/consultations/{consultation.pk}", {"statut": "EXCUSEE"})

    @override_settings(EMAIL_ACTIF=True, EMAIL_PIECE_JOINTE_MAX_MO=0)
    def test_transmission_moa_dossier_trop_lourd_puis_manuel(self):
        dossier = self.json("post", f"/api/projets/{self.projet.pk}/dce/dossiers", {"indice": "A"}, attendu=202)
        envoi = self.json(
            "post", f"/api/projets/{self.projet.pk}/dce/envois/moa",
            {"dossier_id": dossier["id"], "destinataires": "moa@ville.fr; dst@ville.fr", "objet": "DCE", "message": "Bonjour"}, attendu=201,
        )
        self.assertEqual(envoi["statut"], "A_ENVOYER")
        self.assertIn("trop lourd", envoi["erreur"])
        self.assertEqual(envoi["destinataires"], "moa@ville.fr, dst@ville.fr")
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.json("post", f"/api/dce/envois/{envoi['id']}/envoye")["statut"], "ENVOYE")
        self.json(
            "post", f"/api/projets/{self.projet.pk}/dce/envois/moa",
            {"dossier_id": dossier["id"], "destinataires": "pas-une-adresse", "objet": "DCE", "message": "Bonjour"}, attendu=400,
        )

    def test_sans_messagerie_et_marche_public(self):
        self.projet.type_marche = "PUBLIC"
        self.projet.save()
        self.json("post", f"/api/projets/{self.projet.pk}/dce/consultations", {"lot_id": self.lot08.pk, "entreprise_ids": [self.durand.pk]}, attendu=201)
        modeles = self.json("get", f"/api/projets/{self.projet.pk}/dce/messages")
        self.assertIn("profil d'acheteur", modeles["entreprise"]["message"])
        envois = self.json(
            "post", f"/api/projets/{self.projet.pk}/dce/envois/entreprises",
            {"entreprise_ids": [self.durand.pk], **modeles["entreprise"]}, attendu=202,
        )
        envoi = Envoi.objects.get(pk=envois[0]["id"])
        self.assertEqual((envoi.mode, envoi.statut), ("MANUEL", "A_ENVOYER"))
        self.assertIsNone(envoi.dossier)  # marché public : pas de dossier, la plateforme fait foi
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(DossierDCE.objects.count(), 0)


@override_settings(MEDIA_ROOT=DOSSIER_TEST)
class RobustesseDceTests(DceTests):
    """Cas limites relevés à la relecture."""

    def test_noms_longs_indice_et_chemins_windows(self):
        self.projet.nom = "Réhabilitation et extension du groupe scolaire Jules Ferry et création d'un restaurant scolaire"
        self.projet.save()
        self.lot08.intitule = "Menuiseries extérieures aluminium – Occultations – Protections solaires"
        self.lot08.save()
        self.joindre("plan.pdf", categorie="PLANS", lot_id=self.lot08.pk, titre="Carnet de détails des menuiseries extérieures, coupes et élévations")
        dossier = self.json("post", f"/api/projets/{self.projet.pk}/dce/dossiers", {"indice": "B"}, attendu=202)
        dossier = DossierDCE.objects.get(pk=dossier["id"])
        self.assertTrue(dossier.nom.endswith(" - Indice B.zip"), dossier.nom)
        self.assertLessEqual(len(dossier.nom), 75)
        noms = self.zip(dossier.pk).namelist()
        # « Téléchargements\<nom du .zip>\<chemin> » doit rester sous 260 caractères sous Windows.
        self.assertLess(len("C:\\Users\\jdupont\\Downloads\\") + len(dossier.nom) + 1 + max(len(n) for n in noms), 255)

    def test_lots_excuses_exclus_et_lots_figes(self):
        self.durand.lots.add(Lot.objects.get(code="11"))
        self.json("post", f"/api/projets/{self.projet.pk}/dce/consultations", {"lot_id": self.lot08.pk, "entreprise_ids": [self.durand.pk]}, attendu=201)
        self.json("post", f"/api/projets/{self.projet.pk}/dce/consultations", {"lot_id": self.lot11.pk, "entreprise_ids": [self.durand.pk]}, attendu=201)
        excusee = ConsultationEntreprise.objects.get(entreprise=self.durand, lot=self.lot11)
        self.json("patch", f"/api/dce/consultations/{excusee.pk}", {"statut": "EXCUSEE"})
        with override_settings(EMAIL_ACTIF=True):
            self.json("post", f"/api/projets/{self.projet.pk}/dce/envois/entreprises", {"entreprise_ids": [self.durand.pk], "objet": "Consultation – [lots]", "message": "[lots]"}, attendu=202)
        courriel = mail.outbox[0]
        self.assertEqual(courriel.subject, "Consultation – lot 08")
        noms = zipfile.ZipFile(io.BytesIO(courriel.attachments[0][1])).namelist()
        self.assertFalse(any("Lot 11" in n for n in noms))
        self.json("patch", f"/api/dce/consultations/{ConsultationEntreprise.objects.get(entreprise=self.durand, lot=self.lot08).pk}", {"statut": "EXCUSEE"})
        self.json("post", f"/api/projets/{self.projet.pk}/dce/envois/entreprises", {"entreprise_ids": [self.durand.pk], "objet": "x", "message": "x"}, attendu=400)

    def test_envoi_sans_lot_au_moment_de_la_tache(self):
        from .tasks import envoyer_aux_entreprises

        envoi = Envoi.objects.create(projet=self.projet, type_envoi="ENTREPRISE", entreprise=self.durand, destinataires="a@b.fr", objet="o", message="m", mode="MANUEL")
        envoyer_aux_entreprises.apply(args=([envoi.pk], "A", False))
        envoi.refresh_from_db()
        self.assertEqual(envoi.statut, "ERREUR")
        self.assertIn("plus consultée", envoi.erreur)
        self.assertEqual(DossierDCE.objects.count(), 0)

    def test_objet_tres_long_tronque(self):
        self.durand.lots.add(Lot.objects.get(code="11"))
        for lot in (self.lot08, self.lot11):
            self.json("post", f"/api/projets/{self.projet.pk}/dce/consultations", {"lot_id": lot.pk, "entreprise_ids": [self.durand.pk]}, attendu=201)
        envois = self.json("post", f"/api/projets/{self.projet.pk}/dce/envois/entreprises", {"entreprise_ids": [self.durand.pk], "objet": "x" * 248 + " [lots]", "message": "m"}, attendu=202)
        self.assertLessEqual(len(envois[0]["objet"]), 255)

    def test_document_joint_disparu_et_taches_perdues(self):
        from datetime import timedelta

        from django.utils import timezone

        from .models import PieceJointe

        self.joindre("Plan RDC.pdf", categorie="PLANS")
        jointe = PieceJointe.objects.get()
        jointe.fichier.storage.delete(jointe.fichier.name)
        etat = self.json("get", f"/api/projets/{self.projet.pk}/dce")
        self.assertTrue(any(p["niveau"] == "MANQUE" and "Plan RDC" in p["texte"] for p in etat["controle"]))
        dossier = self.json("post", f"/api/projets/{self.projet.pk}/dce/dossiers", {"indice": "A"}, attendu=202)
        dossier = DossierDCE.objects.get(pk=dossier["id"])
        self.assertEqual(dossier.statut, "ERREUR")
        self.assertIn("Plan RDC", dossier.message)

        bloque = DossierDCE.objects.create(projet=self.projet, indice="A")
        DossierDCE.objects.filter(pk=bloque.pk).update(cree_le=timezone.now() - timedelta(hours=2))
        etat = self.json("get", f"/api/projets/{self.projet.pk}/dce")
        self.assertEqual(next(d for d in etat["dossiers"] if d["id"] == bloque.pk)["statut"], "ERREUR")
        self.json("delete", f"/api/dce/dossiers/{bloque.pk}", attendu=204)

    def test_fichiers_effaces_avec_le_projet(self):
        import os

        self.joindre("Plan RDC.pdf", categorie="PLANS")
        dossier = self.json("post", f"/api/projets/{self.projet.pk}/dce/dossiers", {"indice": "A"}, attendu=202)
        chemins = [DossierDCE.objects.get(pk=dossier["id"]).fichier.path] + [j.fichier.path for j in self.projet.pieces_jointes.all()]
        self.assertTrue(all(os.path.exists(c) for c in chemins))
        with self.captureOnCommitCallbacks(execute=True):
            self.projet.delete()
        self.assertFalse(any(os.path.exists(c) for c in chemins))
