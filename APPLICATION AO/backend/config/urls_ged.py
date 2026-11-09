"""Processus public de la GED (adresse Internet) : seules les routes du portail des intervenants.

Ni administration, ni API du cabinet : une erreur de configuration du serveur web ne peut pas
exposer les outils internes par ce processus.
"""
from django.urls import path
from ninja import NinjaAPI

from ged.acces import session_intervenant
from ged.api_portail import construire_router

api_ged = NinjaAPI(title="GED", version="1", urls_namespace="ged_public", docs_url=None, openapi_url=None, auth=session_intervenant)
api_ged.add_router("", construire_router())

urlpatterns = [path("api/", api_ged.urls)]
