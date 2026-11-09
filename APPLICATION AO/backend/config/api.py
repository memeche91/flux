"""Point d'entrée de l'API REST (/api/...). Documentation interactive : /api/docs (administrateurs)."""
from django.contrib.admin.views.decorators import staff_member_required
from ninja import NinjaAPI

from articles.api import router as articles_router
from assistant.api import router as assistant_router
from bibliotheque.api import router as bibliotheque_router
from comptes.api import router as comptes_router
from comptes.securite import session_bureau_etudes
from dce.api import router as dce_router
from entreprises.api import router as entreprises_router
from projets.api import router as projets_router
from projets.api_pieces import router as pieces_router
from referentiel.api import router as referentiel_router

api = NinjaAPI(
    title="Application AO",
    version="0.1.0",
    auth=session_bureau_etudes,
    docs_decorator=staff_member_required,
    urls_namespace="api",
)

api.add_router("/auth", comptes_router)
api.add_router("/referentiel", referentiel_router)
api.add_router("/bibliotheque", bibliotheque_router)
api.add_router("", articles_router)
api.add_router("", projets_router)
api.add_router("", pieces_router)
api.add_router("/assistant", assistant_router)
api.add_router("", entreprises_router)
api.add_router("", dce_router)
