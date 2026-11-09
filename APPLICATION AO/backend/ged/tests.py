import datetime
import io
import json
import shutil
import tempfile
from pathlib import Path

from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from comptes.models import Utilisateur
from dce.models import ConsultationEntreprise, StatutConsultation
from entreprises.models import Contact, Entreprise
from projets.models import LotProjet, Projet
from referentiel.models import Lot

from .acces import MESSAGE_REFUS
from .calendrier import echeance, paques
from .indices import indice_suivant, normaliser_indice, superieur
from .models import Acces, Document, EspaceChantier, Evenement, Intervenant, Notification, Version

DOSSIER_TEST = tempfile.mkdtemp(prefix="application-ao-ged-")
_compteur = [0]


def fichier(nom="plan.pdf", contenu=None):
    """Fichier unique à chaque appel (un même contenu déposé deux fois est refusé)."""
    _compteur[0] += 1
    return SimpleUploadedFile(nom, contenu or f"%PDF-1.4\n% plan {_compteur[0]}\n".encode())


@override_settings(MEDIA_ROOT=DOSSIER_TEST, GED_DISQUE_LIBRE_MIN_GO=0, EMAIL_ACTIF=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", GED_URL_PUBLIQUE="https://ged.cabinet.fr")
class GedTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.moe = Utilisateur.objects.create_user("eco", email="eco@cabinet.fr", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE)
        self.client.force_login(self.moe)
        self.projet = Projet.objects.create(nom="Groupe scolaire les Tilleuls", maitre_oeuvre="Atelier A", maitre_ouvrage="Ville de Saint-Aubin")
        self.lot08 = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="08"), code="08", intitule="Menuiseries extérieures", ordre=1)
        self.lot11 = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="11"), code="11", intitule="Plâtrerie", ordre=2)
        self.durand = Entreprise.objects.create(raison_sociale="Menuiseries Durand", email="contact@durand.fr")
        Contact.objects.create(entreprise=self.durand, nom="Paul Durand", email="paul@durand.fr", principal=True)
        self.martin = Entreprise.objects.create(raison_sociale="Plâtrerie Martin", email="martin@platre.fr")
        for entreprise, lot in ((self.durand, self.lot08), (self.martin, self.lot11)):
            ConsultationEntreprise.objects.create(projet=self.projet, lot=lot, entreprise=entreprise, statut=StatutConsultation.RETENUE)
        self.codes = {}

    # --- utilitaires -------------------------------------------------------------
    def json(self, client, methode, url, donnees=None, attendu=200):
        if methode == "get":
            reponse = client.get(url, donnees or {})
        else:
            with self.captureOnCommitCallbacks(execute=True):
                reponse = getattr(client, methode)(url, json.dumps(donnees or {}), content_type="application/json")
        self.assertEqual(reponse.status_code, attendu, reponse.content)
        return reponse.json() if reponse.content else None

    def poster(self, client, url, donnees, attendu=201):
        with self.captureOnCommitCallbacks(execute=True):
            reponse = client.post(url, donnees)
        self.assertEqual(reponse.status_code, attendu, reponse.content)
        return reponse.json() if reponse.get("Content-Type", "").startswith("application/json") else None

    def ouvrir(self):
        etat = self.json(self.client, "get", f"/api/projets/{self.projet.pk}/ged")
        self.assertIsNone(etat["espace"])
        suggestions = etat["suggestions"]
        self.assertEqual([(s["nom"], [l["code"] for l in s["lots"]]) for s in suggestions], [("Menuiseries Durand", ["08"]), ("Plâtrerie Martin", ["11"])])
        self.assertEqual(suggestions[0]["personnes"], [{"nom": "Paul Durand", "email": "paul@durand.fr"}])
        intervenants = [{"entreprise_id": s["entreprise_id"], "lot_ids": [l["id"] for l in s["lots"]], "personnes": s["personnes"]} for s in suggestions]
        intervenants += [
            {"nom": "Ville de Saint-Aubin", "profil": "MAITRE_OUVRAGE", "personnes": [{"nom": "Service bâtiments", "email": "moa@ville.fr", "frequence": "IMMEDIATE"}]},
            {"nom": "Bureau Véritas", "profil": "CT", "personnes": [{"nom": "Contrôleur", "email": "ct@veritas.fr"}]},
            {"nom": "BET Fluides", "profil": "MOE_EXTERNE", "personnes": [{"nom": "Ingénieure fluides", "email": "bet@fluides.fr"}]},
        ]
        etat = self.json(self.client, "post", f"/api/projets/{self.projet.pk}/ged", {"intervenants": intervenants}, attendu=201)
        self.espace = EspaceChantier.objects.get()
        self.codes = {i["intervenant"]: i["code"] for i in etat["invitations"]}
        return etat

    def portail(self, nom_intervenant) -> Client:
        client = Client()
        self.json(client, "post", "/api/ged/acces", {"code": self.codes[nom_intervenant].lower().replace("-", " ")})
        return client

    def url(self, chemin=""):
        return f"/api/ged/espaces/{self.espace.pk}{chemin}"

    def refs(self, client, url="/api/ged/portail/documents"):
        return sorted(d["reference"] for d in self.json(client, "get", url))

    # --- tests ---------------------------------------------------------------------
    def test_indices_et_calendrier(self):
        self.assertEqual([indice_suivant(i) for i in (None, "A", "Z", "AZ", "ZZ", "0", "1", "9", "A1")], ["A", "B", "AA", "BA", "AAA", "A", "2", "10", "B"])
        self.assertTrue(superieur("A", "0") and superieur("AA", "Z") and superieur("C", "B") and superieur("A1", "A") and superieur("B", "A2"))
        self.assertFalse(superieur("B", "B") or superieur("A", "B") or superieur("2", "A") or superieur("A", "A1"))
        self.assertEqual((normaliser_indice("Ind. b"), normaliser_indice("indice C")), ("B", "C"))
        self.assertEqual((paques(2026), paques(2027)), (datetime.date(2026, 4, 5), datetime.date(2027, 3, 28)))
        self.assertEqual(echeance(datetime.date(2026, 10, 27), 15), datetime.date(2026, 11, 12))  # 11 novembre férié
        self.assertEqual(echeance(datetime.date(2026, 12, 10), 15), datetime.date(2026, 12, 28))  # Noël puis week-end

    def test_ouverture_et_codes_personnels(self):
        etat = self.ouvrir()
        self.assertEqual(len(etat["espace"]["intervenants"]), 5)
        self.assertEqual(etat["espace"]["emails_moe"], ["eco@cabinet.fr"])
        code = self.codes["Menuiseries Durand"]
        self.assertRegex(code, r"^[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}$")
        self.assertIn(f"https://ged.cabinet.fr/ged#code={code}", next(i for i in etat["invitations"] if i["code"] == code)["message"])
        self.assertFalse(Acces.objects.filter(code_empreinte__icontains=code.replace("-", "")).exists())  # jamais en clair
        self.json(self.client, "post", f"/api/projets/{self.projet.pk}/ged", {}, attendu=409)
        # Deuxième personne de la même entreprise : son propre code ; elle peut reprendre les plans de son entreprise.
        durand = Intervenant.objects.get(nom="Menuiseries Durand")
        julie = self.json(self.client, "post", f"/api/ged/intervenants/{durand.pk}/acces", {"nom": "Julie Chef de chantier", "email": "julie@durand.fr"}, attendu=201)
        client_julie = Client()
        espace = self.json(client_julie, "post", "/api/ged/acces", {"code": julie["code"]})
        self.assertEqual(espace["personne"]["nom"], "Julie Chef de chantier")
        paul = self.portail("Menuiseries Durand")
        plan = self.poster(paul, "/api/ged/portail/documents", {"fichier": fichier(), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "EXE"})
        self.assertEqual(plan["versions"][0]["deposee_par"], "Paul Durand (Menuiseries Durand)")
        self.poster(client_julie, f"/api/ged/portail/documents/{plan['id']}/versions", {"fichier": fichier()})
        # Nouvelle invitation : nouveau code pour Julie seule ; l'ancien est refusé, Paul reste connecté.
        renvoi = self.json(self.client, "post", f"/api/ged/acces/{julie['acces_id']}/invitation", {"envoyer": True})
        self.assertTrue(renvoi["envoye"])
        self.assertIn(renvoi["code"], mail.outbox[-1].body)
        self.assertEqual(client_julie.get("/api/ged/portail/documents").status_code, 401)
        erreur = self.json(Client(), "post", "/api/ged/acces", {"code": julie["code"]}, attendu=401)
        self.assertEqual(erreur["detail"], MESSAGE_REFUS)
        self.assertEqual(paul.get("/api/ged/portail/documents").status_code, 200)
        # Désactiver l'intervenant coupe toutes ses personnes ; un espace clos aussi.
        self.json(self.client, "patch", f"/api/ged/intervenants/{durand.pk}", {"actif": False})
        self.assertEqual(paul.get("/api/ged/portail/documents").status_code, 401)
        martin = self.portail("Plâtrerie Martin")
        self.json(self.client, "patch", self.url(), {"statut": "CLOS"})
        self.assertEqual(martin.get("/api/ged/portail/documents").status_code, 401)

    def test_cloisonnement_et_droits(self):
        self.ouvrir()
        self.poster(self.client, self.url("/documents"), {"fichier": fichier("Plan masse.pdf"), "zone": "COMMUN", "categorie": "PLA", "diffusion": "BPE"})
        self.poster(self.client, self.url("/documents"), {"fichier": fichier("Carnet de détails.pdf"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "PLA"})
        os_08 = self.poster(self.client, self.url("/documents"), {"fichier": fichier("OS 1.pdf"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "OS"})
        self.poster(self.client, self.url("/documents"), {"fichier": fichier("Estimation.xlsx", b"PK estimation"), "zone": "MOE", "categorie": "AUT"})
        self.poster(self.client, self.url("/documents"), {"fichier": fichier("page.html", b"<script>"), "zone": "COMMUN", "categorie": "AUT"}, attendu=400)
        self.poster(self.client, self.url("/documents"), {"fichier": fichier("dessin.svg", b"<svg onload=alert(1)>"), "zone": "COMMUN", "categorie": "AUT"}, attendu=400)

        durand, martin = self.portail("Menuiseries Durand"), self.portail("Plâtrerie Martin")
        moa, ct, bet = self.portail("Ville de Saint-Aubin"), self.portail("Bureau Véritas"), self.portail("BET Fluides")
        # Lecture technique entre lots, jamais les pièces confidentielles d'un autre lot ni la zone MOE.
        self.assertEqual(self.refs(durand), ["08-OS-001", "08-PLA-001", "COM-PLA-001"])
        self.assertEqual(self.refs(martin), ["08-PLA-001", "COM-PLA-001"])
        self.assertEqual(self.refs(ct), ["08-PLA-001", "COM-PLA-001"])
        self.assertEqual(self.refs(moa), ["08-OS-001", "08-PLA-001", "COM-PLA-001"])
        self.assertEqual(len(self.refs(bet)), 4)
        version_os = os_08["versions"][0]["id"]
        for quoi in ("fichier", "fiche", "annote"):
            self.assertEqual(martin.get(f"/api/ged/portail/versions/{version_os}/{quoi}").status_code, 404)
        moe = Document.objects.get(zone="MOE").versions.get()
        self.assertEqual(durand.get(f"/api/ged/portail/versions/{moe.pk}/fichier").status_code, 404)
        # Sous-traitant du titulaire : son lot, sans les pièces chiffrées.
        titulaire = Intervenant.objects.get(nom="Menuiseries Durand")
        st = self.json(self.client, "post", self.url("/intervenants"), {"nom": "Pose Express", "lot_ids": [self.lot08.pk], "sous_traitant_de": titulaire.pk, "personnes": [{"nom": "Poseur", "email": "pose@express.fr"}]}, attendu=201)
        self.codes["Pose Express"] = st["invitations"][0]["code"]
        self.assertEqual(self.refs(self.portail("Pose Express")), ["08-PLA-001", "COM-PLA-001"])
        # Cloisonnement strict si l'espace le demande.
        self.json(self.client, "patch", self.url(), {"lecture_inter_lots": False})
        self.assertEqual(self.refs(martin), ["COM-PLA-001"])
        self.json(self.client, "patch", self.url(), {"lecture_inter_lots": True})
        # Les routes du cabinet restent fermées à une session d'intervenant.
        self.assertEqual(durand.get(self.url("/documents")).status_code, 401)
        self.assertEqual(durand.get(f"/api/projets/{self.projet.pk}").status_code, 401)

        # Dépôts : référence attribuée (aucune fuite par la référence), soumis au visa, PDF exigé, jamais ailleurs.
        plan = self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier("EXE fenêtres.pdf"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "EXE",
                                                                   "titre": "Façade nord", "indice": "0", "reference": "MOE-AUT-001", "reference_emetteur": "MEN-EXE-102",
                                                                   "sources": [fichier("EXE fenêtres.dwg", b"AC1032 fenetres")]})
        self.assertEqual((plan["reference"], plan["reference_emetteur"]), ("08-EXE-001", "MEN-EXE-102"))
        self.assertEqual((plan["versions"][0]["visa"], plan["versions"][0]["statut"]), ("EN_ATTENTE", "EN_EXAMEN"))
        self.assertEqual([s["nom_original"] for s in plan["versions"][0]["sources"]], ["EXE fenêtres.dwg"])
        self.assertIsNotNone(plan["versions"][0]["echeance_visa"])
        self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier("EXE.dwg", b"AC1032 x"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "EXE"}, attendu=400)
        self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier(), "zone": "LOT", "lot_id": self.lot11.pk, "categorie": "EXE"}, attendu=403)
        self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier(), "zone": "COMMUN", "categorie": "PLA"}, attendu=403)
        self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier(), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "OS"}, attendu=403)
        self.poster(moa, "/api/ged/portail/documents", {"fichier": fichier(), "zone": "COMMUN", "categorie": "CR"}, attendu=403)
        self.poster(ct, "/api/ged/portail/documents", {"fichier": fichier("RICT.pdf"), "zone": "COMMUN", "categorie": "CT"})
        # Même fichier déposé deux fois : refusé.
        double = fichier("doublon.pdf")
        self.poster(durand, "/api/ged/portail/documents", {"fichier": double, "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "FT"})
        double.seek(0)
        self.poster(durand, "/api/ged/portail/documents", {"fichier": SimpleUploadedFile("autre nom.pdf", double.read()), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "FT"}, attendu=409)

        # Accusé de lecture de l'OS par l'entreprise du lot seulement.
        lu = self.json(durand, "post", f"/api/ged/portail/versions/{version_os}/lecture")
        self.assertIsNotNone(lu["versions"][0]["lu_le"])
        self.json(moa, "post", f"/api/ged/portail/versions/{version_os}/lecture", attendu=403)
        cabinet_os = next(d for d in self.json(self.client, "get", self.url("/documents")) if d["reference"] == "08-OS-001")
        self.assertEqual(cabinet_os["versions"][0]["accuses"][0]["lu_par"], "Paul Durand (Menuiseries Durand)")

        # Journal : l'entreprise ne voit que ce qu'elle peut lire, sans connexions ni téléchargements.
        journal = self.json(martin, "get", "/api/ged/portail/journal")
        self.assertTrue(all("OS" not in e["description"] and "MOE" not in e["description"] for e in journal["resultats"]))
        self.assertTrue(all(e["type"] not in ("CONNEXION", "ACCES", "TELECHARGEMENT") for e in journal["resultats"]))
        self.assertGreater(self.json(self.client, "get", self.url("/journal"))["total"], journal["total"])

    def test_indices_avis_visa_et_statuts(self):
        self.ouvrir()
        durand, bet, ct = self.portail("Menuiseries Durand"), self.portail("BET Fluides"), self.portail("Bureau Véritas")
        plan = self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier("EXE.pdf"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "EXE", "indice": "0"})
        version_0 = plan["versions"][0]["id"]
        # Avis du BET et du CT, invisibles de l'entreprise avant le visa.
        self.poster(bet, f"/api/ged/portail/versions/{version_0}/avis", {"avis": "VAO", "observations": "Prévoir les fourreaux."}, attendu=200)
        self.poster(ct, f"/api/ged/portail/versions/{version_0}/avis", {"avis": "SUSPENDU", "observations": "Note de calcul des fixations attendue."}, attendu=200)
        self.poster(durand, f"/api/ged/portail/versions/{version_0}/avis", {"avis": "VSO"}, attendu=403)
        vu = next(d for d in self.json(durand, "get", "/api/ged/portail/documents") if d["id"] == plan["id"])
        self.assertEqual(vu["versions"][0]["avis"], [])
        # Visa de synthèse : cabinet seulement ; fiche de visa produite.
        self.poster(bet, f"/api/ged/portail/versions/{version_0}/visa", {"statut": "VSO"}, attendu=405)  # aucun visa par le portail
        vise = self.poster(self.client, self.url(f"/versions/{version_0}/visa"), {"statut": "VAO", "commentaire": "Préciser les fixations.\nReprendre les allèges."}, attendu=200)
        self.assertEqual((vise["versions"][0]["visa"], vise["versions"][0]["statut"], vise["versions"][0]["nouvel_indice_attendu"]), ("VAO", "EN_VIGUEUR", True))
        self.assertTrue(vise["versions"][0]["fiche_visa"])
        fiche = durand.get(f"/api/ged/portail/versions/{version_0}/fiche")
        self.assertEqual((fiche.status_code, fiche["Content-Type"]), (200, "application/pdf"))
        vu = next(d for d in self.json(durand, "get", "/api/ged/portail/documents") if d["id"] == plan["id"])
        self.assertEqual(len(vu["versions"][0]["avis"]), 2)
        self.assertEqual(vu["indice_en_vigueur"], "0")
        # Indice A : 0 reste « à utiliser » tant que A n'est pas visé ; A refusé ne remplace rien.
        avec_a = self.poster(durand, f"/api/ged/portail/documents/{plan['id']}/versions", {"fichier": fichier("EXE A.pdf"), "objet": "Reprise des allèges"})
        self.assertEqual([(v["indice"], v["statut"]) for v in avec_a["versions"]], [("A", "EN_EXAMEN"), ("0", "EN_VIGUEUR")])
        self.poster(durand, f"/api/ged/portail/documents/{plan['id']}/versions", {"fichier": fichier(), "indice": "A"}, attendu=400)
        version_a = avec_a["versions"][0]["id"]
        refuse = self.poster(self.client, self.url(f"/versions/{version_a}/visa"), {"statut": "REF", "commentaire": "Non conforme au CCTP."}, attendu=200)
        self.assertEqual([(v["indice"], v["statut"]) for v in refuse["versions"]], [("A", "REFUSEE"), ("0", "EN_VIGUEUR")])
        self.assertIn("REFUSE-NE-PAS-EXECUTER", refuse["versions"][0]["nom_telechargement"])
        # B déposé puis C avant le visa de B : B est remplacé avant visa ; C visé VSO, tout le reste est périmé.
        avec_b = self.poster(durand, f"/api/ged/portail/documents/{plan['id']}/versions", {"fichier": fichier("EXE B.pdf")})
        version_b = avec_b["versions"][0]["id"]
        avec_c = self.poster(durand, f"/api/ged/portail/documents/{plan['id']}/versions", {"fichier": fichier("EXE C.pdf")})
        self.assertEqual(avec_c["versions"][1]["statut"], "REMPLACEE")
        self.poster(self.client, self.url(f"/versions/{version_b}/visa"), {"statut": "VSO"}, attendu=400)
        final = self.poster(self.client, self.url(f"/versions/{avec_c['versions'][0]['id']}/visa"), {"statut": "VSO"}, attendu=200)
        self.assertEqual([v["statut"] for v in final["versions"]], ["EN_VIGUEUR", "REMPLACEE", "REMPLACEE", "REMPLACEE"])
        perime = durand.get(f"/api/ged/portail/versions/{version_0}/fichier")
        self.assertIn("PERIME_08-EXE-001_0_VAO", perime["Content-Disposition"])
        # Indice hors séquence : refusé à l'entreprise, accepté par le cabinet avec un motif.
        self.poster(durand, f"/api/ged/portail/documents/{plan['id']}/versions", {"fichier": fichier(), "indice": "B", "forcer": "erreur"}, attendu=400)
        force = self.poster(self.client, self.url(f"/documents/{plan['id']}/versions"), {"fichier": fichier(), "indice": "B1", "forcer": "Indice du cartouche de l'entreprise"})
        self.assertEqual((force["versions"][0]["indice"], force["versions"][0]["indice_force"]), ("B1", "Indice du cartouche de l'entreprise"))
        # Une autre entreprise ne peut pas ajouter d'indice au document de Durand.
        martin = self.portail("Plâtrerie Martin")
        self.poster(martin, f"/api/ged/portail/documents/{plan['id']}/versions", {"fichier": fichier()}, attendu=403)

    def test_notifications_recepisse_et_recapitulatif(self):
        from .tasks import recapitulatif_quotidien

        self.ouvrir()
        mail.outbox.clear()
        self.poster(self.client, self.url("/documents"), {"fichier": fichier("Plan RDC.pdf"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "PLA"})
        destinataires = sorted(a for m in mail.outbox for a in m.to)
        # Lot 08 : Durand, le MOA (immédiat) et le BET ; pas Martin (autre lot), pas le CT (quotidien), pas l'auteur.
        self.assertEqual(destinataires, ["bet@fluides.fr", "moa@ville.fr", "paul@durand.fr"])
        message = next(m for m in mail.outbox if m.to == ["paul@durand.fr"])
        self.assertIn("https://ged.cabinet.fr/ged/document/", message.body)
        self.assertIn("08-PLA-001", message.body)
        self.assertTrue(message.subject.startswith("[Groupe scolaire les Tilleuls] Lot 08 :"))
        self.assertEqual(Notification.objects.filter(envoyee_le__isnull=False).count(), 3)
        mail.outbox.clear()
        durand = self.portail("Menuiseries Durand")
        self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier("FT menuiserie.pdf"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "FT"})
        recepisse = next(m for m in mail.outbox if "Récépissé" in m.subject)
        self.assertEqual(recepisse.to, ["paul@durand.fr"])
        self.assertIn("SHA-256", recepisse.body)
        self.assertIn("réponse au plus tard le", recepisse.body)
        notifies = sorted(a for m in mail.outbox if "Récépissé" not in m.subject for a in m.to)
        self.assertEqual(notifies, ["bet@fluides.fr", "eco@cabinet.fr", "moa@ville.fr"])
        self.assertIn("à viser", next(m for m in mail.outbox if m.to == ["eco@cabinet.fr"]).subject)
        # Préférence personnelle : récapitulatif quotidien seulement.
        self.json(durand, "patch", "/api/ged/portail/preferences", {"frequence": "QUOTIDIENNE"})
        mail.outbox.clear()
        self.poster(self.client, self.url("/documents"), {"fichier": fichier("Plan 2.pdf"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "PLA"})
        self.assertNotIn("paul@durand.fr", [a for m in mail.outbox for a in m.to])
        # Récapitulatif du matin : nouveautés pour les « quotidiens », visas dus pour la MOE.
        Version.objects.filter(visa="EN_ATTENTE").update(echeance_visa=timezone.localdate() - datetime.timedelta(days=2))
        mail.outbox.clear()
        recapitulatif_quotidien()
        self.assertIn("Plan 2", next(m for m in mail.outbox if m.to == ["paul@durand.fr"]).body)
        self.assertIn("EN RETARD de 2 jour(s)", next(m for m in mail.outbox if m.to == ["eco@cabinet.fr"] and "Visas" in m.subject).body)
        # Notifications coupées : rien n'est envoyé.
        self.json(self.client, "patch", self.url(), {"notifications": False})
        mail.outbox.clear()
        self.poster(self.client, self.url("/documents"), {"fichier": fichier(), "zone": "COMMUN", "categorie": "CR"})
        self.assertEqual([m for m in mail.outbox if "Récépissé" not in m.subject], [])

    def test_reception(self):
        self.ouvrir()
        durand = self.portail("Menuiseries Durand")
        self.json(self.client, "patch", self.url(), {"statut": "RECEPTION"}, attendu=400)
        self.json(self.client, "patch", self.url(), {"statut": "RECEPTION", "date_reception": "2027-06-30"})
        self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier(), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "EXE"}, attendu=403)
        self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier("Notice.pdf"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "DOE"})

    def test_fichiers_servis_sans_risque_registre_et_suppression(self):
        from openpyxl import load_workbook

        self.ouvrir()
        pdf = self.poster(self.client, self.url("/documents"), {"fichier": fichier("Plan.pdf"), "zone": "COMMUN", "categorie": "PLA"})
        dwg = self.poster(self.client, self.url("/documents"), {"fichier": fichier("Plan.dwg", b"AC1032 plan"), "zone": "COMMUN", "categorie": "PLA"})
        faux = self.poster(self.client, self.url("/documents"), {"fichier": fichier("faux.pdf", b"<html><script>alert(1)</script></html>"), "zone": "COMMUN", "categorie": "AUT"})
        texte = self.poster(self.client, self.url("/documents"), {"fichier": fichier("notes.txt", b"<script>alert(1)</script>"), "zone": "COMMUN", "categorie": "AUT"})
        reponse = self.client.get(self.url(f"/versions/{pdf['versions'][0]['id']}/fichier"))
        self.assertEqual((reponse["Content-Type"], reponse["Content-Disposition"].split(";")[0], reponse["X-Content-Type-Options"]), ("application/pdf", "inline", "nosniff"))
        for doc in (dwg, texte):
            reponse = self.client.get(self.url(f"/versions/{doc['versions'][0]['id']}/fichier"))
            self.assertEqual((reponse["Content-Type"], reponse["Content-Disposition"].split(";")[0]), ("application/octet-stream", "attachment"))
        self.assertEqual(self.client.get(self.url(f"/versions/{faux['versions'][0]['id']}/fichier"))["Content-Type"], "application/pdf")  # jamais text/html
        martin = self.portail("Plâtrerie Martin")
        reponse = martin.get(f"/api/ged/portail/versions/{texte['versions'][0]['id']}/fichier")
        self.assertEqual(reponse["Content-Type"], "application/octet-stream")
        # Fichier retiré du disque (antivirus) : message explicite.
        Path(Version.objects.get(document_id=pdf["id"]).fichier.path).rename(Path(DOSSIER_TEST) / "quarantaine.pdf")
        self.assertEqual(self.client.get(self.url(f"/versions/{pdf['versions'][0]['id']}/fichier")).status_code, 410)
        # Annulation : le document reste dans l'historique.
        annule = self.json(self.client, "patch", self.url(f"/documents/{dwg['id']}"), {"annule": True, "motif_annulation": "Remplacé par le plan PDF"})
        self.assertTrue(annule["annule"])
        self.poster(self.client, self.url(f"/documents/{dwg['id']}/versions"), {"fichier": fichier("Plan B.dwg", b"AC1032 B")}, attendu=403)
        classeur = load_workbook(io.BytesIO(self.client.get(self.url("/registre.xlsx")).content))
        valeurs = [c for ligne in classeur.active.iter_rows(values_only=True) for c in ligne if c]
        self.assertIn("COM-PLA-002", valeurs)
        self.assertIn("Annulé", valeurs)
        # Suppression du projet : fichiers effacés du disque.
        chemin = Path(Version.objects.get(document_id=dwg["id"]).fichier.path)
        self.assertTrue(chemin.exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.projet.delete()
        self.assertFalse(chemin.exists())
        self.assertFalse(Evenement.objects.exists())


@override_settings(MEDIA_ROOT=DOSSIER_TEST, GED_DISQUE_LIBRE_MIN_GO=0, ROOT_URLCONF="config.urls_ged")
class ProcessusPublicTests(TestCase):
    """Le processus public ne sert que le portail : ni API du cabinet, ni administration."""

    def test_seules_les_routes_du_portail(self):
        client = Client()
        for chemin in ("/api/projets", "/api/auth/csrf", "/admin/", "/api/", "/api/docs", "/api/openapi.json", "/api/ged/espaces/1/documents"):
            self.assertEqual(client.get(chemin).status_code, 404, chemin)
        self.assertEqual(client.get("/api/ged/portail/csrf").status_code, 200)
        self.assertEqual(client.get("/api/ged/portail/documents").status_code, 401)
        self.assertEqual(client.post("/api/ged/acces", json.dumps({"code": "AAAA-BBBB-CCCC"}), content_type="application/json").status_code, 401)
