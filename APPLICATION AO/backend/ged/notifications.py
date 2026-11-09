"""Courriels de la GED : un message groupé par destinataire pour les nouveautés d'un espace.

Destinataires d'un événement : intervenants actifs, abonnés, qui ont accès au document
(une entreprise n'est jamais prévenue d'un document d'un autre lot ni de la zone MOE),
et courriels de la maîtrise d'œuvre ; jamais l'auteur de l'action.
"""
from __future__ import annotations

from collections import defaultdict

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone
from django.utils.formats import date_format

from .droits import acteur_intervenant, peut_voir
from .models import EspaceChantier, Evenement, StatutVisa, TypeEvenement, Zone


def _lieu(document) -> str:
    if document.zone == Zone.LOT and document.lot_id:
        return f"Lot {document.lot.code}"
    return "Maîtrise d'œuvre" if document.zone == Zone.MOE else "Commun"


def ligne_evenement(evenement: Evenement) -> str:
    quand = date_format(timezone.localtime(evenement.date), "d/m H:i")
    document = evenement.document
    texte = f"- {quand} – {evenement.get_type_display()}"
    if document is not None:
        texte += f" – {_lieu(document)} – {evenement.description}"
    else:
        texte += f" – {evenement.description}"
    texte += f" ({evenement.acteur})"
    if evenement.version is not None and evenement.type in (TypeEvenement.DEPOT, TypeEvenement.INDICE) and evenement.version.visa == StatutVisa.EN_ATTENTE:
        texte += " – soumis au visa de la maîtrise d'œuvre"
    return texte


def destinataires(espace: EspaceChantier, evenement: Evenement, intervenants) -> dict[str, str]:
    """Adresse (minuscules) → nom du destinataire."""
    resultat: dict[str, str] = {}
    document = evenement.document
    for intervenant in intervenants:
        if intervenant.pk == evenement.intervenant_id:
            continue  # pas de courriel pour sa propre action
        if document is not None and not peut_voir(acteur_intervenant(intervenant), document):
            continue
        for adresse in intervenant.liste_emails():
            resultat.setdefault(adresse.lower(), intervenant.nom)
    for adresse in espace.liste_emails_moe():
        resultat.setdefault(adresse.lower(), "Maîtrise d'œuvre")
    return resultat


def messages_groupes(espace: EspaceChantier, evenements: list[Evenement]) -> list[EmailMessage]:
    intervenants = list(espace.intervenants.filter(actif=True, notifications=True).prefetch_related("lots"))
    par_destinataire: dict[str, list[Evenement]] = defaultdict(list)
    for evenement in evenements:
        for adresse in destinataires(espace, evenement, intervenants):
            par_destinataire[adresse].append(evenement)
    projet = espace.projet
    lien = (settings.GED_URL_PUBLIQUE or settings.URL_APPLICATION).rstrip("/") + "/ged"
    moe = set(a.lower() for a in espace.liste_emails_moe())
    messages = []
    for adresse, liste in par_destinataire.items():
        lien_destinataire = f"{settings.URL_APPLICATION.rstrip('/')}/projets/{projet.pk}/ged" if adresse in moe else lien
        objet = f"[{projet.nom}] " + (f"{len(liste)} nouveautés" if len(liste) > 1 else liste[0].get_type_display()) + " sur l'espace documentaire du chantier"
        corps = "\n".join([
            "Bonjour,",
            "",
            f"Nouveautés sur l'espace documentaire du chantier « {projet.nom} » :",
            "",
            *[ligne_evenement(e) for e in liste],
            "",
            f"Consulter les documents : {lien_destinataire}",
            *([] if adresse in moe else ["(avec le code d'accès personnel qui vous a été remis)"]),
            "",
            "Bien cordialement,",
            "",
            projet.maitre_oeuvre or "La maîtrise d'œuvre",
        ])
        messages.append(EmailMessage(objet[:200], corps, settings.DEFAULT_FROM_EMAIL, [adresse]))
    return messages


def envoyer(messages: list[EmailMessage]) -> int:
    if not messages:
        return 0
    with get_connection(fail_silently=False) as connexion:
        return connexion.send_messages(messages)
