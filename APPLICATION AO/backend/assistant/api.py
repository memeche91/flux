"""API de l'assistant IA local (réservée à l'administrateur)."""
from __future__ import annotations

import base64
import datetime
from pathlib import Path

from celery.exceptions import TimeoutError as DelaiDepasse

from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from ninja import Field, File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from projets.models import Projet

from . import ollama, voix
from .conversation import repondre
from .models import Conversation, EtatIndexation, Passage
from .tasks import indexer_assistant, synthetiser_texte, transcrire_audio

router = Router(tags=["Assistant IA"])

TAILLE_MAX_AUDIO = 10 * 1024 * 1024
TEXTE_MAX_SYNTHESE = 4000
DELAI_VOIX = 300


def _administrateur(request) -> None:
    if not getattr(request.auth, "est_administrateur", False):
        raise HttpError(403, "L'assistant est réservé à l'administrateur.")


def _conversation(request, conversation_id: int) -> Conversation:
    _administrateur(request)
    return get_object_or_404(Conversation.objects.select_related("projet"), pk=conversation_id, utilisateur=request.auth)


# --- Schémas -------------------------------------------------------------------------


class ProjetCourt(Schema):
    id: int
    nom: str


class ConversationResume(Schema):
    id: int
    titre: str
    projet: ProjetCourt | None
    modifie_le: datetime.datetime


class MessageOut(Schema):
    id: int
    role: str
    texte: str
    sources: list[dict]
    interrompu: bool
    cree_le: datetime.datetime


class ConversationDetail(ConversationResume):
    messages: list[MessageOut]


class NouvelleConversation(Schema):
    projet_id: int | None = None


class ModificationConversation(Schema):
    titre: str | None = Field(None, min_length=1, max_length=200)
    projet_id: int | None = None


class Question(Schema):
    texte: str = Field(..., min_length=1, max_length=4000)


class Synthese(Schema):
    texte: str = Field(..., min_length=1, max_length=20000)


def _resume(conversation: Conversation) -> dict:
    return {
        "id": conversation.pk,
        "titre": conversation.titre,
        "projet": {"id": conversation.projet.pk, "nom": conversation.projet.nom} if conversation.projet else None,
        "modifie_le": conversation.modifie_le,
    }


def _detail(conversation: Conversation) -> dict:
    return {
        **_resume(conversation),
        "messages": [
            {"id": m.pk, "role": m.role, "texte": m.texte, "sources": m.sources, "interrompu": m.interrompu, "cree_le": m.cree_le}
            for m in conversation.messages.all()
        ],
    }


# --- État ----------------------------------------------------------------------------


@router.get("/etat")
def etat(request):
    _administrateur(request)
    from django.conf import settings

    version = ollama.version()
    installes = ollama.modeles_installes() if version else set()
    index = EtatIndexation.courant()
    passages = Passage.objects.count()
    a_jour = Passage.objects.filter(modele=settings.IA_MODELE_EMBEDDING, vecteur__isnull=False).count()
    return {
        "moteur": {
            "joignable": version is not None,
            "version": version,
            "modele": settings.IA_MODELE,
            "modele_installe": ollama.est_installe(settings.IA_MODELE, installes),
            "embedding": settings.IA_MODELE_EMBEDDING,
            "embedding_installe": ollama.est_installe(settings.IA_MODELE_EMBEDDING, installes),
        },
        "voix": {
            "transcription": settings.IA_WHISPER,
            "transcription_installee": voix.transcription_installee(),
            "synthese": settings.IA_VOIX,
            "synthese_installee": voix.synthese_installee(),
        },
        "index": {
            "passages": passages,
            "a_jour": a_jour,
            "en_cours": index.en_cours and not index.perime(),
            "total": index.total,
            "faits": index.faits,
            "message": index.message,
            "fin": index.fin,
        },
    }


@router.post("/indexer", response={202: dict})
def indexer(request):
    _administrateur(request)
    indexer_assistant.delay()
    return 202, {"detail": "Indexation lancée."}


# --- Conversations -------------------------------------------------------------------


@router.get("/conversations", response=list[ConversationResume])
def lister(request):
    _administrateur(request)
    return [_resume(c) for c in Conversation.objects.filter(utilisateur=request.auth).select_related("projet")[:200]]


@router.post("/conversations", response={201: ConversationDetail})
def creer(request, donnees: NouvelleConversation):
    _administrateur(request)
    projet = get_object_or_404(Projet, pk=donnees.projet_id) if donnees.projet_id else None
    conversation = Conversation.objects.create(utilisateur=request.auth, titre="Nouvelle conversation", projet=projet)
    return 201, _detail(conversation)


@router.get("/conversations/{conversation_id}", response=ConversationDetail)
def detail(request, conversation_id: int):
    return _detail(_conversation(request, conversation_id))


@router.patch("/conversations/{conversation_id}", response=ConversationDetail)
def modifier(request, conversation_id: int, donnees: ModificationConversation):
    conversation = _conversation(request, conversation_id)
    champs = donnees.model_dump(exclude_unset=True)
    if champs.get("titre"):
        conversation.titre = " ".join(champs["titre"].split())[:200] or conversation.titre
    if "projet_id" in champs:
        conversation.projet = get_object_or_404(Projet, pk=champs["projet_id"]) if champs["projet_id"] else None
    conversation.save()
    return _detail(conversation)


@router.delete("/conversations/{conversation_id}", response={204: None})
def supprimer(request, conversation_id: int):
    _conversation(request, conversation_id).delete()
    return 204, None


@router.post("/conversations/{conversation_id}/messages")
def poser_question(request, conversation_id: int, donnees: Question):
    conversation = _conversation(request, conversation_id)
    texte = donnees.texte.strip()
    if not texte:
        raise HttpError(400, "La question est vide.")
    reponse = StreamingHttpResponse(repondre(conversation, texte), content_type="application/x-ndjson; charset=utf-8")
    reponse["Cache-Control"] = "no-cache, no-transform"
    reponse["X-Accel-Buffering"] = "no"
    return reponse


# --- Voix ----------------------------------------------------------------------------


@router.post("/transcrire")
def transcrire(request, audio: File[UploadedFile]):
    _administrateur(request)
    if audio.size and audio.size > TAILLE_MAX_AUDIO:
        raise HttpError(413, "Enregistrement trop long : dictez votre question en moins de 10 minutes.")
    suffixe = Path(audio.name or "audio.webm").suffix.lower()
    if suffixe not in {".webm", ".ogg", ".m4a", ".mp4", ".wav", ".mp3"}:
        raise HttpError(400, "Format audio non reconnu.")
    contenu = base64.b64encode(audio.read()).decode("ascii")
    try:
        texte = transcrire_audio.delay(contenu, suffixe).get(timeout=DELAI_VOIX)
    except DelaiDepasse:
        raise HttpError(503, "La transcription ne répond pas. Vérifiez que le service « voix » est démarré.") from None
    except Exception as erreur:  # noqa: BLE001 - format audio illisible, modèle absent…
        raise HttpError(400, f"Transcription impossible ({erreur.__class__.__name__}).") from None
    return {"texte": texte}


@router.post("/synthese")
def synthese(request, donnees: Synthese):
    _administrateur(request)
    try:
        audio = synthetiser_texte.delay(donnees.texte[:TEXTE_MAX_SYNTHESE]).get(timeout=DELAI_VOIX)
    except DelaiDepasse:
        raise HttpError(503, "La lecture à voix haute ne répond pas. Vérifiez que le service « voix » est démarré.") from None
    except Exception as erreur:  # noqa: BLE001
        raise HttpError(503, f"Lecture à voix haute indisponible ({erreur.__class__.__name__}).") from None
    return HttpResponse(base64.b64decode(audio), content_type="audio/wav")
