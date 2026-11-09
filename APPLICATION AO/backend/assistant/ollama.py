"""Client minimal de l'API Ollama (moteur d'IA local)."""
from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
from django.conf import settings


class OllamaIndisponible(Exception):
    pass


def _url(chemin: str) -> str:
    return f"{settings.OLLAMA_URL}{chemin}"


def _client(delai: float | None = 10.0) -> httpx.Client:
    # Ollama tourne sur le réseau local (conteneur voisin) : jamais de proxy.
    return httpx.Client(timeout=httpx.Timeout(delai, connect=5.0), trust_env=False)


def version() -> str | None:
    try:
        with _client(3.0) as client:
            return client.get(_url("/api/version")).raise_for_status().json().get("version")
    except (httpx.HTTPError, ValueError):
        return None


def modeles_installes() -> set[str]:
    try:
        with _client(5.0) as client:
            donnees = client.get(_url("/api/tags")).raise_for_status().json()
    except (httpx.HTTPError, ValueError):
        return set()
    noms = set()
    for modele in donnees.get("models", []):
        nom = modele.get("name", "")
        noms.add(nom)
        if nom.endswith(":latest"):
            noms.add(nom.removesuffix(":latest"))
    return noms


def est_installe(nom: str, installes: set[str] | None = None) -> bool:
    installes = modeles_installes() if installes is None else installes
    return nom in installes or f"{nom}:latest" in installes


def vectoriser(textes: list[str]) -> list[list[float]]:
    """Plongements (embeddings) des textes, dans l'ordre."""
    if not textes:
        return []
    try:
        with _client(600.0) as client:
            reponse = client.post(
                _url("/api/embed"),
                json={"model": settings.IA_MODELE_EMBEDDING, "input": textes, "keep_alive": "30m", "truncate": True},
            )
            reponse.raise_for_status()
            return reponse.json()["embeddings"]
    except (httpx.HTTPError, KeyError, ValueError) as erreur:
        raise OllamaIndisponible(_explication(erreur)) from erreur


def discuter(messages: list[dict], *, temperature: float = 0.3) -> Iterator[str]:
    """Réponse du modèle de conversation, morceau par morceau."""
    corps = {
        "model": settings.IA_MODELE,
        "messages": messages,
        "stream": True,
        "think": False,
        "keep_alive": "30m",
        "options": {"temperature": temperature, "num_ctx": settings.IA_CONTEXTE},
    }
    try:
        with _client(None) as client:
            for tentative in range(2):
                with client.stream("POST", _url("/api/chat"), json=corps) as reponse:
                    if reponse.status_code == 400 and tentative == 0 and "think" in corps:
                        # Modèle sans mode « réflexion » : on relance sans l'option.
                        reponse.read()
                        corps.pop("think")
                        continue
                    if reponse.status_code >= 400:
                        reponse.read()
                        raise OllamaIndisponible(_detail(reponse))
                    for ligne in reponse.iter_lines():
                        if not ligne:
                            continue
                        donnees = json.loads(ligne)
                        if donnees.get("error"):
                            raise OllamaIndisponible(donnees["error"])
                        morceau = donnees.get("message", {}).get("content", "")
                        if morceau:
                            yield morceau
                        if donnees.get("done"):
                            return
                return
    except httpx.HTTPError as erreur:
        raise OllamaIndisponible(_explication(erreur)) from erreur


def telecharger(nom: str) -> Iterator[dict]:
    """Télécharge un modèle dans Ollama ; renvoie la progression ({"status", "completed", "total"})."""
    with _client(None) as client:
        with client.stream("POST", _url("/api/pull"), json={"model": nom, "stream": True}) as reponse:
            reponse.raise_for_status()
            for ligne in reponse.iter_lines():
                if ligne:
                    donnees = json.loads(ligne)
                    if donnees.get("error"):
                        raise OllamaIndisponible(donnees["error"])
                    yield donnees


def _detail(reponse: httpx.Response) -> str:
    try:
        return reponse.json().get("error") or f"Erreur {reponse.status_code} du moteur d'IA."
    except ValueError:
        return f"Erreur {reponse.status_code} du moteur d'IA."


def _explication(erreur: Exception) -> str:
    if isinstance(erreur, httpx.ConnectError):
        return "Le moteur d'IA (Ollama) ne répond pas. Vérifiez qu'il est démarré."
    if isinstance(erreur, httpx.HTTPStatusError):
        return _detail(erreur.response)
    return f"Échange avec le moteur d'IA impossible ({erreur.__class__.__name__})."
