import hashlib
import json
from decimal import Decimal
from unittest import mock

import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from articles.models import Article, LignePrix
from articles.normalisation import normaliser
from bibliotheque.models import DocumentReference
from comptes.models import Utilisateur
from projets.models import LotProjet, Projet

from . import ollama
from .indexation import synchroniser
from .models import Conversation, EtatIndexation, Message, Passage, SourcePassage
from .recherche import rechercher
from .tasks import indexer_assistant
from .voix import texte_pour_voix

DIMENSION = 256


def faux_vecteurs(textes):
    """Plongements de test : sac de mots haché (des textes proches ont des vecteurs proches)."""
    resultat = []
    for texte in textes:
        vecteur = np.zeros(DIMENSION, dtype=np.float32)
        for mot in normaliser(texte).split():
            if len(mot) >= 3:
                vecteur[int(hashlib.md5(mot.encode()).hexdigest(), 16) % DIMENSION] += 1
        resultat.append(vecteur.tolist() if vecteur.any() else [1.0] + [0.0] * (DIMENSION - 1))
    return resultat


def document(type_document, nom, **champs):
    return DocumentReference.objects.create(
        type_document=type_document,
        fichier=f"essais/{nom}",
        nom_original=nom,
        taille=1,
        empreinte_sha256=hashlib.sha256(nom.encode()).hexdigest(),
        statut_analyse="ANALYSE",
        **champs,
    )


class Donnees(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user("admin", password="mot-de-passe-solide-42", role=Utilisateur.Role.ADMINISTRATEUR)
        self.client.force_login(self.admin)
        self.cctp = document("CCTP", "CCTP Lot 08.docx", operation="Groupe scolaire", annee=2024)
        self.fenetres = Article.objects.create(
            document=self.cctp, ordre=1, numero="8.2.1", titre="Fenêtres aluminium à rupture de pont thermique", niveau=3,
            contenu="Fourniture et pose de fenêtres en aluminium oscillo-battantes, vitrage 4/16/4, Uw ≤ 1,3 W/m².K.",
            categorie="OUVRAGE", texte_recherche="fenetres aluminium",
        )
        Article.objects.create(
            document=self.cctp, ordre=2, numero="8.3", titre="Plâtrerie et cloisons", niveau=2,
            contenu="Cloisons de distribution en plaques de plâtre 72/48 selon le DTU 25.41.",
            categorie="OUVRAGE", texte_recherche="platrerie",
        )
        dpgf = document("DPGF", "DPGF Lot 08.xlsx", operation="Médiathèque", annee=2025)
        for indice, prix in enumerate(["2450", "2300", "2600"]):
            LignePrix.objects.create(
                document=dpgf, ordre=indice, designation="Porte-fenêtre aluminium 2 vantaux", unite="U", unite_normalisee="u",
                prix_unitaire=Decimal(prix), designation_normalisee="porte fenetre aluminium 2 vantaux",
            )


@mock.patch("assistant.ollama.vectoriser", side_effect=faux_vecteurs)
class IndexationTests(Donnees):
    def test_synchronisation_et_recherche(self, _vectoriser):
        # Même ouvrage relevé sous un chapitre dans une autre DPGF : un seul groupe de prix.
        LignePrix.objects.create(
            document=document("DPGF", "DPGF Lot 08 bis.xlsx", annee=2023), ordre=1, designation="Porte-fenêtre aluminium 2 vantaux",
            unite="u", unite_normalisee="u", prix_unitaire=Decimal("2500"),
            designation_normalisee="8 2 menuiseries porte fenetre aluminium 2 vantaux",
        )
        indexer_assistant.apply()
        etat = EtatIndexation.courant()
        self.assertFalse(etat.en_cours)
        self.assertEqual(etat.message, "Index à jour.")
        sources = set(Passage.objects.values_list("source", flat=True))
        self.assertEqual(sources, {SourcePassage.ARTICLE, SourcePassage.PRIX, SourcePassage.MODELE})
        self.assertEqual(Passage.objects.filter(source=SourcePassage.ARTICLE).count(), 2)
        self.assertEqual(Passage.objects.filter(source=SourcePassage.PRIX).count(), 1)
        self.assertFalse(Passage.objects.filter(vecteur__isnull=True).exists())

        extraits = rechercher("Quel prix pour une porte-fenêtre aluminium 2 vantaux ?")
        prix = [e for e in extraits if e.passage.source == SourcePassage.PRIX]
        self.assertEqual(len(prix), 1)
        self.assertEqual(prix[0].statistiques["mediane"], 2475.0)
        self.assertEqual(prix[0].statistiques["nombre"], 4)
        self.assertEqual([e.numero for e in extraits], list(range(1, len(extraits) + 1)))

        premier = rechercher("fenêtres aluminium oscillo-battantes vitrage")[0]
        self.assertEqual(premier.passage.article_id, self.fenetres.pk)

    def test_texte_modifie_et_article_supprime(self, _vectoriser):
        indexer_assistant.apply()
        self.fenetres.contenu = "Texte entièrement réécrit."
        self.fenetres.save()
        a_calculer = synchroniser()
        self.assertEqual(Passage.objects.filter(pk__in=a_calculer).get().article_id, self.fenetres.pk)
        identifiant = self.fenetres.pk
        self.fenetres.delete()
        synchroniser()
        self.assertFalse(Passage.objects.filter(article_id=identifiant).exists())
        self.assertFalse(Passage.objects.filter(cle=f"article:{identifiant}").exists())

    def test_modeles_du_cabinet_indexes(self, _vectoriser):
        from projets.models import ModelePiece

        ModelePiece.objects.create(
            nom="CCAP maison", type_piece="CCAP", marche="PUBLIC",
            clauses=[
                {"genre": "CHAPITRE", "titre": "Garanties", "contenu": ""},
                {"genre": "ARTICLE", "titre": "Garantie de parfait achèvement", "contenu": "<p>Le délai de garantie est d'un an.</p>"},
            ],
        )
        synchroniser()
        passage = Passage.objects.get(source=SourcePassage.MODELE, meta__origine="CABINET")
        self.assertIn("Garanties › Garantie de parfait achèvement", passage.texte)
        self.assertIn("d'un an", passage.texte)

    def test_indexation_sans_moteur(self, vectoriser):
        vectoriser.side_effect = ollama.OllamaIndisponible("Le moteur d'IA (Ollama) ne répond pas.")
        indexer_assistant.apply()
        etat = EtatIndexation.courant()
        self.assertFalse(etat.en_cours)
        self.assertIn("ne répond pas", etat.message)


@mock.patch("assistant.ollama.vectoriser", side_effect=faux_vecteurs)
class ConversationTests(Donnees):
    def flux(self, conversation_id, texte):
        reponse = self.client.post(f"/api/assistant/conversations/{conversation_id}/messages", json.dumps({"texte": texte}), content_type="application/json")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/x-ndjson; charset=utf-8")
        return [json.loads(ligne) for ligne in b"".join(reponse.streaming_content).decode().splitlines() if ligne.strip()]

    def test_question_reponse_en_flux(self, _vectoriser):
        indexer_assistant.apply()
        projet = Projet.objects.create(nom="Groupe scolaire", maitre_ouvrage="Ville de Saint-Aubin", procedure="MAPA")
        LotProjet.objects.create(projet=projet, code="08", intitule="Menuiseries extérieures")
        conversation = self.client.post("/api/assistant/conversations", json.dumps({"projet_id": projet.pk}), content_type="application/json").json()

        envoyes = []

        def discuter(messages, **_):
            envoyes.extend(messages)
            yield "La médiane est de **2 450 € HT** "
            yield "[1]."

        with mock.patch("assistant.ollama.discuter", side_effect=discuter):
            evenements = self.flux(conversation["id"], "Quel prix pour une porte-fenêtre aluminium 2 vantaux ?")

        types = [e["type"] for e in evenements]
        self.assertEqual(types[0], "etape")
        self.assertIn("sources", types)
        self.assertEqual(types[-1], "fin")
        texte = "".join(e["texte"] for e in evenements if e["type"] == "texte")
        self.assertEqual(texte, "La médiane est de **2 450 € HT** [1].")
        sources = next(e["sources"] for e in evenements if e["type"] == "sources")
        self.assertTrue(any(s["type"] == "PRIX" and "2 450,00 €" in s["detail"] for s in sources))

        consigne = envoyes[-1]["content"]
        self.assertIn("PROJET EN COURS « Groupe scolaire »", consigne)
        self.assertIn("Lot 08 – Menuiseries extérieures", consigne)
        self.assertIn("médiane 2 450,00 € HT", consigne)
        self.assertEqual(envoyes[0]["role"], "system")

        detail = self.client.get(f"/api/assistant/conversations/{conversation['id']}").json()
        self.assertEqual(detail["titre"], "Quel prix pour une porte-fenêtre aluminium 2 vantaux ?")
        self.assertEqual([m["role"] for m in detail["messages"]], ["user", "assistant"])
        self.assertTrue(detail["messages"][1]["sources"])

        # La question suivante transmet l'historique.
        envoyes.clear()
        with mock.patch("assistant.ollama.discuter", side_effect=discuter):
            self.flux(conversation["id"], "Et pour une fenêtre ?")
        self.assertEqual([m["role"] for m in envoyes], ["system", "user", "assistant", "user"])

    def test_moteur_indisponible_et_reponse_interrompue(self, _vectoriser):
        conversation = Conversation.objects.create(utilisateur=self.admin, titre="Nouvelle conversation")

        def coupe(messages, **_):
            yield "Début de réponse"
            raise ollama.OllamaIndisponible("Le moteur d'IA (Ollama) ne répond pas.")

        with mock.patch("assistant.ollama.discuter", side_effect=coupe):
            evenements = self.flux(conversation.pk, "Question ?")
        self.assertEqual(evenements[-1], {"type": "erreur", "message": "Le moteur d'IA (Ollama) ne répond pas."})
        message = Message.objects.get(conversation=conversation, role="assistant")
        self.assertTrue(message.interrompu)
        self.assertEqual(message.texte, "Début de réponse")

    def test_reserve_a_l_administrateur_et_a_ses_conversations(self, _vectoriser):
        conversation = Conversation.objects.create(utilisateur=self.admin, titre="Privée")
        moe = Utilisateur.objects.create_user("moe", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE)
        self.client.force_login(moe)
        self.assertEqual(self.client.get("/api/assistant/conversations").status_code, 403)
        self.assertEqual(self.client.get("/api/assistant/etat").status_code, 403)
        autre_admin = Utilisateur.objects.create_user("admin2", password="mot-de-passe-solide-42", role=Utilisateur.Role.ADMINISTRATEUR)
        self.client.force_login(autre_admin)
        self.assertEqual(self.client.get(f"/api/assistant/conversations/{conversation.pk}").status_code, 404)
        self.assertEqual(self.client.get("/api/assistant/conversations").json(), [])

    def test_etat_sans_moteur(self, _vectoriser):
        with mock.patch("assistant.ollama.version", return_value=None):
            etat = self.client.get("/api/assistant/etat").json()
        self.assertFalse(etat["moteur"]["joignable"])
        self.assertFalse(etat["moteur"]["modele_installe"])
        self.assertIn("passages", etat["index"])

    def test_conversations_crud(self, _vectoriser):
        cree = self.client.post("/api/assistant/conversations", "{}", content_type="application/json").json()
        modifiee = self.client.patch(
            f"/api/assistant/conversations/{cree['id']}", json.dumps({"titre": "  Prix  menuiseries "}), content_type="application/json"
        ).json()
        self.assertEqual(modifiee["titre"], "Prix menuiseries")
        self.assertEqual(len(self.client.get("/api/assistant/conversations").json()), 1)
        self.assertEqual(self.client.delete(f"/api/assistant/conversations/{cree['id']}").status_code, 204)
        reponse = self.client.post(f"/api/assistant/conversations/{cree['id']}/messages", json.dumps({"texte": "x"}), content_type="application/json")
        self.assertEqual(reponse.status_code, 404)

    def test_voix(self, _vectoriser):
        with mock.patch("assistant.voix.transcrire", return_value="Quel prix pour une porte-fenêtre ?") as transcrire:
            reponse = self.client.post("/api/assistant/transcrire", {"audio": SimpleUploadedFile("q.webm", b"audio", content_type="audio/webm")})
        self.assertEqual(reponse.json(), {"texte": "Quel prix pour une porte-fenêtre ?"})
        self.assertTrue(str(transcrire.call_args.args[0]).endswith(".webm"))
        with mock.patch("assistant.voix.synthetiser", return_value=b"RIFF....WAVE") as synthetiser:
            reponse = self.client.post("/api/assistant/synthese", json.dumps({"texte": "Bonjour"}), content_type="application/json")
        self.assertEqual(reponse["Content-Type"], "audio/wav")
        self.assertEqual(reponse.content, b"RIFF....WAVE")
        synthetiser.assert_called_once_with("Bonjour")


@mock.patch("assistant.ollama.vectoriser", side_effect=faux_vecteurs)
class RobustesseTests(Donnees):
    def test_indexation_perimee_reprise_et_tranches(self, _vectoriser):
        from datetime import timedelta

        from django.utils import timezone

        from . import tasks

        EtatIndexation.objects.update_or_create(pk=1, defaults={"en_cours": True, "battement": timezone.now() - timedelta(hours=1)})
        with mock.patch.object(tasks, "PASSAGES_PAR_TRANCHE", 50):
            indexer_assistant.apply()
        etat = EtatIndexation.courant()
        self.assertFalse(etat.en_cours)
        self.assertEqual(etat.message, "Index à jour.")
        self.assertEqual(etat.faits, etat.total)
        self.assertFalse(Passage.objects.filter(vecteur__isnull=True).exists())

    def test_indexation_en_cours_recente_non_doublee(self, _vectoriser):
        from django.utils import timezone

        EtatIndexation.objects.update_or_create(pk=1, defaults={"en_cours": True, "battement": timezone.now()})
        indexer_assistant.apply()
        self.assertTrue(EtatIndexation.courant().relancer)
        self.assertFalse(Passage.objects.exists())

    def test_conversation_supprimee_pendant_la_reponse(self, _vectoriser):
        from .conversation import repondre

        conversation = Conversation.objects.create(utilisateur=self.admin, titre="Nouvelle conversation")

        def reponse(messages, **_):
            yield "Réponse"

        evenements = []
        with mock.patch("assistant.ollama.discuter", side_effect=reponse):
            for ligne in repondre(conversation, "Question ?"):
                evenements.append(json.loads(ligne))
                if evenements[-1]["type"] == "sources":
                    Conversation.objects.filter(pk=conversation.pk).delete()  # supprimée pendant la réponse
        self.assertEqual(evenements[-1]["type"], "fin")
        self.assertFalse(Message.objects.exists())


class VoixTests(SimpleTestCase):
    def test_texte_pour_voix(self):
        self.assertEqual(
            texte_pour_voix("**Prix** : 2 450 € HT [1], Uw ≤ 1,3 W/m²\n- DPGF du lot 08 [2, 3]"),
            "Prix : 2450 euros hors taxes , Uw inférieur ou égal à 1,3 W/ mètres carrés D P G F du lot 08",
        )
