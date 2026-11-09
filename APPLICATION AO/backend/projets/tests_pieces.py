import io
import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from comptes.models import Utilisateur
from referentiel.models import Lot

from . import modeles
from .champs import champs_du_projet, champs_utilises, remplacer_champs, remplacer_dans_titre
from .models import LotProjet, ModelePiece, OptionLot, Projet

DOSSIER_TEST = tempfile.mkdtemp(prefix="application-ao-pieces-")

CLAUSES_MODELE = [
    {"genre": "CHAPITRE", "titre": "Objet du marché", "contenu": ""},
    {"genre": "ARTICLE", "titre": "Objet", "contenu": "<p>Le marché porte sur {{nom_operation}} pour {{maitre_ouvrage}}.</p>"},
    {"genre": "ARTICLE", "titre": "Allotissement", "contenu": "<p>Les lots sont les suivants :</p><p>{{liste_lots}}</p>"},
    {"genre": "CHAPITRE", "titre": "Délais", "contenu": "<p>Offres remises au plus tard le {{date_limite_offres}}.</p>"},
    {"genre": "ARTICLE", "titre": "Critères", "contenu": "{{criteres_jugement}}<p>Champ {{inexistant}}.</p>"},
]


def ccap_docx() -> bytes:
    from docx import Document

    document = Document()
    for texte, gras in [
        ("ARTICLE 1 – OBJET DU MARCHÉ", True),
        ("Le présent marché porte sur des travaux de réhabilitation.", False),
        ("ARTICLE 2 – PÉNALITÉS", True),
        ("2.1 Pénalités de retard", False),
        ("Une pénalité de 1/3000e du montant du marché est appliquée par jour de retard.", False),
    ]:
        paragraphe = document.add_paragraph()
        paragraphe.add_run(texte).bold = gras
    flux = io.BytesIO()
    document.save(flux)
    return flux.getvalue()


def ccap_docx_styles() -> bytes:
    """Ancien CCAP rédigé avec les styles Titre de Word et trois niveaux de titres."""
    from docx import Document

    document = Document()
    for texte, niveau in [
        ("ARTICLE 1 – OBJET DU MARCHÉ", 1),
        ("Le marché porte sur des travaux de réhabilitation.", None),
        ("1.1 Contenu du marché", 2),
        ("Le marché comprend les travaux tous corps d'état.", None),
        ("ARTICLE 2 – PRIX", 1),
        ("Les prix sont établis hors taxes et en euros.", None),
        ("2.1 Forme des prix", 2),
        ("Les prix sont fermes et actualisables.", None),
        ("2.1.1 Actualisation des prix", 3),
        ("Les prix sont actualisés par application de l'index BT01.", None),
        ("2.2 Règlement des comptes", 2),
        ("Les acomptes sont versés mensuellement à l'entreprise.", None),
    ]:
        if niveau:
            document.add_heading(texte, level=niveau)
        else:
            document.add_paragraph(texte)
    flux = io.BytesIO()
    document.save(flux)
    return flux.getvalue()


@override_settings(MEDIA_ROOT=DOSSIER_TEST)
class PiecesTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        self.utilisateur = Utilisateur.objects.create_user("economiste", password="mot-de-passe-solide-42")
        self.client.force_login(self.utilisateur)
        self.projet = Projet.objects.create(nom="Groupe scolaire <Tilleuls>", maitre_ouvrage="Ville de Saint-Aubin", procedure="Procédure adaptée")
        self.lot08 = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="08"), code="08", intitule="Menuiseries extérieures", ordre=1)
        self.lot11 = LotProjet.objects.create(projet=self.projet, code="11", intitule="Plâtrerie", ordre=2)
        OptionLot.objects.create(lot=self.lot08, libelle="Volets roulants")
        self.modele = ModelePiece.objects.create(nom="CCAP du cabinet", type_piece="CCAP", clauses=CLAUSES_MODELE)

    def json(self, methode, url, donnees=None, attendu=200):
        if methode == "get":
            reponse = self.client.get(url, donnees or {})
        else:
            reponse = getattr(self.client, methode)(url, json.dumps(donnees or {}), content_type="application/json")
        self.assertEqual(reponse.status_code, attendu, reponse.content)
        return reponse.json() if reponse.content else None

    # --- Consultation et champs ---

    def test_consultation_valeurs_par_defaut_et_ponderation(self):
        consultation = self.json("get", f"/api/projets/{self.projet.pk}/consultation")
        self.assertEqual(sum(c["ponderation"] for c in consultation["criteres"]), 100)
        self.assertTrue(any("environnement" in c["libelle"] for c in consultation["criteres"]))
        consultation["criteres"] = [{"libelle": "Prix", "ponderation": 60}, {"libelle": "Valeur technique", "ponderation": 30}]
        erreur = self.json("put", f"/api/projets/{self.projet.pk}/consultation", consultation, attendu=400)
        self.assertIn("90 %", erreur["detail"])
        consultation["criteres"][1]["ponderation"] = 40
        consultation["date_limite_offres"] = "2027-01-11T12:00:00"
        consultation["visite"] = "OBLIGATOIRE"
        self.json("put", f"/api/projets/{self.projet.pk}/consultation", consultation)
        champs = champs_du_projet(self.projet)
        self.assertEqual(champs["date_limite_offres"].apercu, "lundi 11 janvier 2027 à 12 h 00")
        self.assertIn("obligatoire", champs["visite_site"].apercu)

    def test_remplacement_des_champs(self):
        champs = champs_du_projet(self.projet, self.lot08)
        html = remplacer_champs("<p>{{nom_operation}} – {{date_limite_offres}}</p><p>{{liste_lots}}</p><p>{{lot_pse}}</p><p>{{x_y}}</p>", champs)
        self.assertIn("Groupe scolaire &lt;Tilleuls&gt;", html)  # valeur échappée
        self.assertIn("[à compléter : Date limite de remise des offres]", html)
        self.assertIn("<ul><li>Lot 08 – Menuiseries extérieures</li><li>Lot 11 – Plâtrerie</li></ul>", html)
        self.assertNotIn("<p><ul>", html)  # le paragraphe du champ « bloc » est remplacé
        self.assertIn("PSE n°1 – Volets roulants", html)
        self.assertIn("champ inconnu « x_y »", html)
        self.assertEqual(remplacer_dans_titre("Lot {{lot_code}} – {{lot_intitule}}", champs), "Lot 08 – Menuiseries extérieures")

    # --- Pièces ---

    def test_creation_depuis_un_modele_et_numerotation(self):
        piece = self.json("post", f"/api/projets/{self.projet.pk}/pieces", {"type_piece": "CCAP", "modele_id": f"cabinet-{self.modele.pk}"}, attendu=201)
        self.assertEqual(
            [(c["numero"], c["titre"]) for c in piece["clauses"]],
            [("Article 1", "Objet du marché"), ("1.1", "Objet"), ("1.2", "Allotissement"), ("Article 2", "Délais"), ("2.1", "Critères")],
        )
        self.assertEqual(piece["origine"], "Modèle : CCAP du cabinet")
        self.json("post", f"/api/projets/{self.projet.pk}/pieces", {"type_piece": "CCAP"}, attendu=409)
        self.json("post", f"/api/projets/{self.projet.pk}/pieces", {"type_piece": "AE"}, attendu=409)

        actes = self.json("post", f"/api/projets/{self.projet.pk}/pieces/actes-engagement", {}, attendu=201)
        self.assertEqual([a["lot"]["code"] for a in actes], ["08", "11"])
        self.assertEqual(self.json("post", f"/api/projets/{self.projet.pk}/pieces/actes-engagement", {}, attendu=201), [])
        self.assertEqual(len(self.json("get", f"/api/projets/{self.projet.pk}/pieces")), 3)

    def test_clauses_ajout_modification_deplacement_suppression(self):
        piece = self.json("post", f"/api/projets/{self.projet.pk}/pieces", {"type_piece": "RC", "modele_id": f"cabinet-{self.modele.pk}"}, attendu=201)
        objet = piece["clauses"][0]["id"]
        detail = self.json("post", f"/api/pieces/{piece['id']}/clauses", {"titre": "Nouvelle clause", "apres_id": objet}, attendu=201)
        self.assertEqual(detail["clauses"][1]["titre"], "Nouvelle clause")
        nouvelle = detail["clauses"][1]["id"]
        detail = self.json("patch", f"/api/clauses/{nouvelle}", {"contenu": '<p onclick="x()">Texte<script>alert(1)</script></p>'})
        self.assertEqual(detail["clauses"][1]["contenu"], "<p>Texte</p>")
        delais = next(c["id"] for c in detail["clauses"] if c["titre"] == "Délais")
        detail = self.json("post", f"/api/clauses/{delais}/deplacer", {"sens": "haut"})
        self.assertEqual([c["titre"] for c in detail["clauses"]][:2], ["Délais", "Critères"])
        detail = self.json("delete", f"/api/clauses/{nouvelle}")
        self.assertNotIn("Nouvelle clause", [c["titre"] for c in detail["clauses"]])

    def test_reprise_d_un_ancien_ccap_de_la_bibliotheque(self):
        with self.captureOnCommitCallbacks(execute=True):
            document = self.client.post(
                "/api/bibliotheque/documents", {"fichier": SimpleUploadedFile("CCAP ancien.docx", ccap_docx()), "type_document": "CCAP"}
            ).json()
        piece = self.json("post", f"/api/projets/{self.projet.pk}/pieces", {"type_piece": "CCAP", "document_id": document["id"]}, attendu=201)
        self.assertEqual(
            [(c["genre"], c["numero"], c["titre"]) for c in piece["clauses"]],
            [("CHAPITRE", "Article 1", "OBJET DU MARCHÉ"), ("CHAPITRE", "Article 2", "PÉNALITÉS"), ("ARTICLE", "2.1", "Pénalités de retard")],
        )
        self.assertIn("1/3000e", piece["clauses"][2]["contenu"])

    def test_modeles_du_cabinet(self):
        piece = self.json("post", f"/api/projets/{self.projet.pk}/pieces", {"type_piece": "CCAP", "modele_id": f"cabinet-{self.modele.pk}"}, attendu=201)
        modele = self.json("post", f"/api/pieces/{piece['id']}/enregistrer-modele", {"nom": "Mon CCAP 2027"}, attendu=201)
        self.assertEqual(modele["nb_clauses"], 5)
        noms = [m["nom"] for m in self.json("get", "/api/modeles", {"type_piece": "CCAP"})]
        self.assertIn("Mon CCAP 2027", noms)
        self.json("delete", f"/api/modeles/{modele['id']}", attendu=204)
        self.json("delete", "/api/modeles/base-CCAP-PUBLIC", attendu=400)

    def test_exports_word_et_pdf(self):
        import pdfplumber
        from docx import Document

        piece = self.json("post", f"/api/projets/{self.projet.pk}/pieces", {"type_piece": "CCAP", "modele_id": f"cabinet-{self.modele.pk}"}, attendu=201)
        reponse = self.client.get(f"/api/pieces/{piece['id']}/export/docx")
        self.assertEqual(reponse.status_code, 200)
        document = Document(io.BytesIO(reponse.content))
        titres = [(p.style.name, p.text) for p in document.paragraphs if p.style.name.startswith("Heading")]
        self.assertIn(("Heading 1", "Article 1 – Objet du marché"), titres)
        self.assertIn(("Heading 2", "1.2 Allotissement"), titres)
        texte = "\n".join(p.text for p in document.paragraphs)
        self.assertIn("Groupe scolaire <Tilleuls> pour Ville de Saint-Aubin", texte)
        self.assertIn("[à compléter : Date limite de remise des offres]", texte)

        reponse = self.client.get(f"/api/pieces/{piece['id']}/export/pdf")
        with pdfplumber.open(io.BytesIO(reponse.content)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        self.assertIn("CAHIER DES CLAUSES ADMINISTRATIVES PARTICULIÈRES", " ".join(pages[0].upper().split()))
        self.assertIn("Sommaire", pages[1])
        self.assertIn("Lot 08 – Menuiseries extérieures", "\n".join(pages))
        self.assertIn("Valeur technique", "\n".join(pages))  # tableau des critères

        acte = self.json("post", f"/api/projets/{self.projet.pk}/pieces", {"type_piece": "AE", "lot_id": self.lot08.pk}, attendu=201)
        reponse = self.client.get(f"/api/pieces/{acte['id']}/export/pdf")
        with pdfplumber.open(io.BytesIO(reponse.content)) as pdf:
            self.assertIn("Lot 08 – Menuiseries extérieures", pdf.pages[0].extract_text())


    def test_reprise_d_un_document_a_styles_et_trois_niveaux(self):
        with self.captureOnCommitCallbacks(execute=True):
            document = self.client.post(
                "/api/bibliotheque/documents", {"fichier": SimpleUploadedFile("CCAP styles.docx", ccap_docx_styles()), "type_document": "CCAP"}
            ).json()
        piece = self.json("post", f"/api/projets/{self.projet.pk}/pieces", {"type_piece": "CCAP", "document_id": document["id"]}, attendu=201)
        self.assertEqual(
            [(c["numero"], c["titre"]) for c in piece["clauses"]],
            [
                ("Article 1", "OBJET DU MARCHÉ"),
                ("1.1", "Contenu du marché"),
                ("Article 2", "PRIX"),
                ("2.1", "Forme des prix"),
                ("2.2", "Actualisation des prix"),
                ("2.3", "Règlement des comptes"),
            ],
        )

    def test_nouvel_article_apres_un_article_garde_ses_sous_articles(self):
        piece = self.json("post", f"/api/projets/{self.projet.pk}/pieces", {"type_piece": "CCAP", "modele_id": f"cabinet-{self.modele.pk}"}, attendu=201)
        objet = piece["clauses"][0]["id"]  # « Article 1 – Objet du marché », suivi de 1.1 et 1.2
        detail = self.json("post", f"/api/pieces/{piece['id']}/clauses", {"genre": "CHAPITRE", "titre": "Nouvel article", "apres_id": objet}, attendu=201)
        self.assertEqual(
            [(c["numero"], c["titre"]) for c in detail["clauses"]][:4],
            [("Article 1", "Objet du marché"), ("1.1", "Objet"), ("1.2", "Allotissement"), ("Article 2", "Nouvel article")],
        )
        # Un sous-article, lui, se place juste après la sélection.
        detail = self.json("post", f"/api/pieces/{piece['id']}/clauses", {"titre": "Sous-article", "apres_id": objet}, attendu=201)
        self.assertEqual(detail["clauses"][1]["titre"], "Sous-article")

    def test_champs_bloc_dans_une_phrase_et_entites(self):
        self.projet.nom = "Construction d'un gymnase & école"
        self.projet.adresse_operation = "12 rue de l'Église\n74000 Annecy"
        self.projet.save()
        champs = champs_du_projet(self.projet)
        self.assertEqual(champs["nom_operation"].apercu, "Construction d'un gymnase & école")
        self.assertEqual(champs["adresse_operation"].apercu, "12 rue de l'Église 74000 Annecy")
        self.assertEqual(remplacer_dans_titre("Objet : {{nom_operation}}", champs), "Objet : Construction d'un gymnase & école")
        self.assertEqual(remplacer_dans_titre("{{Nom_Operation}} {{inconnu}}", champs), "Construction d'un gymnase & école [champ inconnu « inconnu »]")
        html = remplacer_champs("<p>Les critères sont : <strong>{{criteres_jugement}}</strong> ci-dessus.</p>", champs)
        self.assertTrue(html.startswith("<p>Les critères sont : </p><table>"), html)
        self.assertIn("<p> ci-dessus.</p>", html)
        self.assertNotIn("data-", html)
        self.assertIn("champ inconnu « Date-Limite »", remplacer_champs("<p>{{Date-Limite}}</p>", champs))

    def test_caracteres_de_controle_et_identifiants_de_modele(self):
        from docx import Document

        piece = self.json("post", f"/api/projets/{self.projet.pk}/pieces", {"type_piece": "CCAP"}, attendu=201)
        detail = self.json("post", f"/api/pieces/{piece['id']}/clauses", {"titre": "Titre\x0bavec tabulation", "contenu": "<p>Texte\x01 collé</p>"}, attendu=201)
        self.assertEqual(detail["clauses"][-1]["titre"], "Titre avec tabulation")
        self.assertEqual(detail["clauses"][-1]["contenu"], "<p>Texte collé</p>")
        self.json("post", f"/api/pieces/{piece['id']}/clauses", {"titre": "   "}, attendu=400)
        self.projet.maitre_ouvrage = "Ville\x0cde Saint-Aubin\x01"
        self.projet.save()
        reponse = self.client.get(f"/api/pieces/{piece['id']}/export/docx")
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("Ville de Saint-Aubin".upper(), "\n".join(p.text for p in Document(io.BytesIO(reponse.content)).paragraphs))
        self.json("delete", "/api/modeles/cabinet-%C2%B2", attendu=400)
        self.json("delete", "/api/modeles/cabinet-999999", attendu=404)


class ModelesDeBaseTests(TestCase):
    """Intégrité des modèles fournis avec l'application."""

    def test_modeles_de_base_complets_et_champs_connus(self):
        projet = Projet.objects.create(nom="Test")
        lot = LotProjet.objects.create(projet=projet, code="08", intitule="Menuiseries")
        connus = set(champs_du_projet(projet, lot))
        base = modeles.modeles_de_base()
        self.assertEqual(
            sorted((m["type_piece"], m["marche"]) for m in base),
            [("AE", "PRIVE"), ("AE", "PUBLIC"), ("CCAP", "PRIVE"), ("CCAP", "PUBLIC"), ("RC", "PRIVE"), ("RC", "PUBLIC")],
        )
        for modele in base:
            textes = [c["titre"] for c in modele["clauses"]] + [c["contenu"] for c in modele["clauses"]]
            inconnus = champs_utilises(textes) - connus
            self.assertFalse(inconnus, f"{modele['id']} utilise des champs inconnus : {inconnus}")
            self.assertGreater(len(modele["clauses"]), 5, modele["id"])
            self.assertEqual(modele["clauses"][0]["genre"], "CHAPITRE", modele["id"])
