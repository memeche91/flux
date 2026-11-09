"""Préparation des messages pour le modèle et réponse en flux continu."""
from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Iterator
from decimal import Decimal

from django.utils import timezone

from projets.champs import champs_du_projet
from projets.models import Projet
from projets.structure import structurer

from . import ollama
from .models import Conversation, Message
from .recherche import formater_extrait, rechercher, source_pour_interface
from .textes import tronquer

logger = logging.getLogger(__name__)

SYSTEME = """Tu es l'assistant d'un économiste de la construction dans un cabinet d'architecture en France. Nous sommes le {date}.
Réponds en français, de façon précise et concise, avec le vocabulaire des marchés de travaux.

Règles impératives :
1. Appuie-toi sur les EXTRAITS fournis (documents du cabinet, modèles de pièces vérifiés, prix relevés dans ses DPGF) et sur le PROJET EN COURS s'il est décrit. Cite le numéro de l'extrait entre crochets, par exemple [2], après chaque information qui en provient.
2. Ne cite JAMAIS un numéro d'article (loi, code, décret, CCAG), une norme, un DTU, un prix ou un chiffre qui ne figure pas dans les extraits ou le projet. Si la réponse n'y est pas, dis-le en une phrase, donne au plus la règle générale si tu en es certain, sans numéro, et conseille de vérifier sur Légifrance.
3. Pour rédiger (article de CCTP, clause, courrier), donne directement le texte prêt à coller, dans le style des documents du cabinet (mêmes tournures, même niveau de détail), adapté à l'ouvrage demandé (matériau, usage). N'ajoute ni prix ni commentaire si on ne te les demande pas. Écris « [à préciser] » pour toute caractéristique que tu ne connais pas, plutôt que de l'inventer.
4. Un prix d'un ouvrage différent (autre matériau, autre dimension) ne sert que d'ordre de grandeur, et tu le dis.
5. Les textes des normes et DTU sont payants : ne prétends pas les citer mot pour mot.
6. Mise en forme : paragraphes courts, listes à puces si utile, **gras** pour les montants et les points clés. Pas de tableau, pas de titre de niveau 1."""

AUCUN_EXTRAIT = "Aucun extrait pertinent n'a été trouvé dans les documents du cabinet pour cette question."
HISTORIQUE_MAX = 4
SIGNE_DE_VIE = 2.0  # secondes : une ligne d'attente permet de voir vite que l'utilisateur est parti


def _euros(valeur: Decimal) -> str:
    return f"{valeur:,.2f}".replace(",", " ").replace(".", ",") + " € HT"


def description_projet(projet: Projet) -> str:
    champs = champs_du_projet(projet)
    utiles = [
        "nom_operation", "maitre_ouvrage", "procedure", "date_limite_offres", "duree_validite_offres", "delai_execution",
        "date_debut_travaux", "forme_prix", "index_reference", "taux_retenue_garantie", "taux_avance", "penalites_retard",
        "criteres_jugement", "variantes", "visite_site",
    ]
    lignes = [f"- Marché {'public' if projet.type_marche == 'PUBLIC' else 'privé'}, phase {projet.phase}, indice {projet.indice}."]
    for cle in utiles:
        champ = champs.get(cle)
        if champ and champ.renseigne and champ.apercu:
            lignes.append(f"- {champ.libelle} : {champ.apercu}")
    for lot in projet.lots.prefetch_related("options").order_by("ordre", "code"):
        structure = structurer(lot)
        options = ", ".join(f"{o.nom_court} {o.libelle}" for o in lot.options.all())
        lignes.append(
            f"- Lot {lot.code} – {lot.intitule} : estimation {_euros(structure.total_base)} (solution de base)"
            + (f" ; options : {options}" if options else "")
        )
    pieces = ", ".join(sorted({p.get_type_piece_display() for p in projet.pieces.all()}))
    if pieces:
        lignes.append(f"- Pièces administratives rédigées : {pieces}.")
    return tronquer("\n".join(lignes), 1800)


def preparer(conversation: Conversation, question: str) -> tuple[list[dict], list[dict]]:
    """Messages pour le modèle et sources affichées dans l'interface."""
    extraits = rechercher(question)
    blocs = []
    if conversation.projet_id:
        blocs.append(f"PROJET EN COURS « {conversation.projet.nom} » :\n{description_projet(conversation.projet)}")
    blocs.append("EXTRAITS :\n" + ("\n\n".join(formater_extrait(e) for e in extraits) if extraits else AUCUN_EXTRAIT))
    blocs.append(f"QUESTION : {question}")

    messages = [{"role": "system", "content": SYSTEME.format(date=timezone.localdate().strftime("%d/%m/%Y"))}]
    precedents = list(conversation.messages.exclude(texte="").order_by("-cree_le", "-id")[1 : HISTORIQUE_MAX + 1])[::-1]
    for message in precedents:
        messages.append({"role": message.role, "content": tronquer(message.texte, 900)})
    messages.append({"role": "user", "content": "\n\n".join(blocs)})
    return messages, [source_pour_interface(e) for e in extraits]


def _ligne(donnees: dict) -> bytes:
    return (json.dumps(donnees, ensure_ascii=False) + "\n").encode("utf-8")


def _produire(messages: list[dict], file: queue.Queue, controle: dict) -> None:
    """Fil de lecture d'Ollama : dépose les morceaux dans la file, puis « fin » ou « erreur »."""
    try:
        for morceau in ollama.discuter(messages, controle=controle):
            if controle.get("arret"):
                return
            file.put(("texte", morceau))
        file.put(("fin", None))
    except ollama.OllamaIndisponible as erreur:
        file.put(("erreur", str(erreur)))
    except Exception:  # noqa: BLE001 - y compris la connexion fermée volontairement
        if not controle.get("arret"):
            logger.exception("Réponse de l'assistant impossible")
            file.put(("erreur", "L'assistant a rencontré une erreur. Réessayez."))


def repondre(conversation: Conversation, question: str) -> Iterator[bytes]:
    """Flux NDJSON : {"type": "sources"}, puis des {"type": "texte"}, puis {"type": "fin"} ou {"type": "erreur"}.

    Des lignes {"type": "attente"} sont envoyées pendant le calcul : si l'utilisateur a arrêté
    la réponse, l'écriture échoue aussitôt et le calcul d'Ollama est interrompu.
    """
    Message.objects.create(conversation=conversation, role=Message.Role.UTILISATEUR, texte=question)
    if conversation.titre == "Nouvelle conversation":
        conversation.titre = tronquer(question.replace("\n", " "), 80)
    conversation.save(update_fields=["titre", "modifie_le"])

    envoyes: list[str] = []
    sources: list[dict] = []
    termine = False
    controle: dict = {}
    try:
        yield _ligne({"type": "etape", "texte": "Recherche dans vos documents…"})
        try:
            messages, sources = preparer(conversation, question)
        except ollama.OllamaIndisponible as erreur:
            yield _ligne({"type": "erreur", "message": str(erreur)})
            return
        yield _ligne({"type": "sources", "sources": sources})
        yield _ligne({"type": "etape", "texte": "Rédaction de la réponse…"})

        file: queue.Queue = queue.Queue()
        threading.Thread(target=_produire, args=(messages, file, controle), daemon=True).start()
        while True:
            try:
                genre, valeur = file.get(timeout=SIGNE_DE_VIE)
            except queue.Empty:
                yield _ligne({"type": "attente"})
                continue
            if genre == "texte":
                yield _ligne({"type": "texte", "texte": valeur})
                envoyes.append(valeur)
            elif genre == "erreur":
                yield _ligne({"type": "erreur", "message": valeur})
                break
            else:
                termine = True
                break
    except Exception:  # noqa: BLE001 - l'utilisateur doit toujours recevoir un message
        logger.exception("Réponse de l'assistant impossible")
        yield _ligne({"type": "erreur", "message": "L'assistant a rencontré une erreur. Réessayez."})
    finally:
        # Aussi exécuté quand l'utilisateur arrête la réponse : Ollama est libéré et le texte
        # déjà affiché est conservé.
        controle["arret"] = True
        client = controle.get("client")
        if client is not None:
            client.close()
        texte = "".join(envoyes).strip()
        message_id = None
        if texte and Conversation.objects.filter(pk=conversation.pk).exists():
            message_id = Message.objects.create(
                conversation=conversation, role=Message.Role.ASSISTANT, texte=texte, sources=sources, interrompu=not termine
            ).pk
    if termine:
        yield _ligne({"type": "fin", "message_id": message_id})
