import json

from django.test import TestCase

from .models import Utilisateur


class ConnexionTests(TestCase):
    def setUp(self):
        Utilisateur.objects.create_user("economiste", password="mot-de-passe-solide-42", first_name="Jeanne")
        Utilisateur.objects.create_user(
            "entreprise", password="mot-de-passe-solide-42", role=Utilisateur.Role.ENTREPRISE
        )
        self.client = self.client_class(enforce_csrf_checks=True)

    def connecter(self, identifiant, mot_de_passe):
        jeton = self.client.get("/api/auth/csrf").json()["csrftoken"]
        return self.client.post(
            "/api/auth/connexion",
            json.dumps({"identifiant": identifiant, "mot_de_passe": mot_de_passe}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=jeton,
        )

    def test_connexion_puis_profil_puis_deconnexion(self):
        reponse = self.connecter("economiste", "mot-de-passe-solide-42")
        self.assertEqual(reponse.status_code, 200, reponse.content)
        self.assertEqual(reponse.json()["nom_complet"], "Jeanne")

        moi = self.client.get("/api/auth/moi")
        self.assertEqual(moi.status_code, 200)
        self.assertEqual(moi.json()["role"], "MOE")

        deconnexion = self.client.post(
            "/api/auth/deconnexion", HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value
        )
        self.assertEqual(deconnexion.status_code, 204)
        self.assertEqual(self.client.get("/api/auth/moi").status_code, 401)

    def test_mauvais_mot_de_passe(self):
        self.assertEqual(self.connecter("economiste", "faux").status_code, 401)

    def test_compte_entreprise_sans_acces_cabinet(self):
        self.assertEqual(self.connecter("entreprise", "mot-de-passe-solide-42").status_code, 403)

    def test_connexion_sans_jeton_csrf_refusee(self):
        reponse = self.client.post(
            "/api/auth/connexion",
            json.dumps({"identifiant": "economiste", "mot_de_passe": "mot-de-passe-solide-42"}),
            content_type="application/json",
        )
        self.assertEqual(reponse.status_code, 403)
