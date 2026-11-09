"""Courriels de la GED.

- Nouveautés : un message groupé par destinataire. Une entreprise n'est prévenue que pour le
  Commun et ses lots (jamais un document d'un autre lot, de la zone MOE ou un avis interne) ;
  les intervenants en « récapitulatif quotidien » les reçoivent le lendemain matin.
- Récépissé de dépôt : envoyé à l'intervenant qui dépose (date, empreinte, échéance de visa).
- Récapitulatif quotidien : nouveautés de la veille, visas dus et en retard (MOE), ordres de
  service non lus (relance).
Chaque envoi est enregistré (Notification) : preuve de diffusion.
"""
from __future__ import annotations

import datetime
from collections import defaultdict

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone
from django.utils.formats import date_format

from .droits import acteur_intervenant, concerne
from .models import (
    Acces,
    AccuseLecture,
    Diffusion,
    EspaceChantier,
    Evenement,
    Frequence,
    Notification,
    StatutVisa,
    TypeEvenement,
    Version,
    Zone,
)

EVENEMENTS_INTERNES = {TypeEvenement.AVIS, TypeEvenement.LECTURE}  # pour la maîtrise d'œuvre seulement
MESSAGES_PAR_MINUTE = 20  # Microsoft 365 en accepte 30


def a_viser(evenement: Evenement) -> bool:
    """Ce qui appelle une action de la maîtrise d'œuvre : document à viser, avis, accusé de lecture."""
    if evenement.type in EVENEMENTS_INTERNES:
        return True
    version = evenement.version
    return evenement.type in (TypeEvenement.DEPOT, TypeEvenement.INDICE) and version is not None and version.diffusion == Diffusion.POUR_VISA


def _lieu(document) -> str:
    if document.zone == Zone.LOT and document.lot_id:
        return f"Lot {document.lot.code}"
    return "Maîtrise d'œuvre" if document.zone == Zone.MOE else "Commun"


def ligne_evenement(evenement: Evenement) -> str:
    quand = date_format(timezone.localtime(evenement.date), "d/m H:i")
    document = evenement.document
    texte = f"- {quand} – {evenement.get_type_display()}"
    texte += f" – {_lieu(document)} – {evenement.description}" if document is not None else f" – {evenement.description}"
    texte += f" ({evenement.acteur})"
    version = evenement.version
    if version is not None and evenement.type in (TypeEvenement.DEPOT, TypeEvenement.INDICE):
        if version.diffusion == Diffusion.POUR_VISA and version.echeance_visa:
            texte += f" – soumis au visa, réponse attendue le {version.echeance_visa:%d/%m/%Y}"
        precedente = version.document.versions.filter(deposee_le__lt=version.deposee_le).order_by("-deposee_le").first()
        if precedente is not None and version.diffusion != Diffusion.POUR_VISA:
            texte += f" – remplace l'indice {precedente.indice}"
    if version is not None and evenement.type == TypeEvenement.VISA and version.visa in (StatutVisa.VSO, StatutVisa.VAO):
        precedente = version.document.versions.filter(deposee_le__lt=version.deposee_le).order_by("-deposee_le").first()
        if precedente is not None:
            texte += f" – l'indice {precedente.indice} est remplacé"
    return texte


def _lien(adresse_moe: bool, projet, document_id: int | None = None) -> str:
    if adresse_moe:
        return f"{settings.URL_APPLICATION.rstrip('/')}/projets/{projet.pk}/ged" + (f"?document={document_id}" if document_id else "")
    return (settings.GED_URL_PUBLIQUE or settings.URL_APPLICATION).rstrip("/") + "/ged" + (f"/document/{document_id}" if document_id else "")


def _message(projet, adresse: str, objet: str, lignes: list[str], moe: bool, document_id: int | None = None) -> EmailMessage:
    corps = "\n".join([
        "Bonjour,", "", *lignes, "",
        f"Consulter {'le document' if document_id else 'les documents'} : {_lien(moe, projet, document_id)}",
        *([] if moe else ["(avec le code d'accès personnel qui vous a été remis)"]),
        "", "Bien cordialement,", "", projet.maitre_oeuvre or "La maîtrise d'œuvre",
    ])
    return EmailMessage(objet[:200], corps, settings.DEFAULT_FROM_EMAIL, [adresse])


def destinataires(espace: EspaceChantier, evenement: Evenement, acces_actifs, frequence: str) -> dict[str, Acces | None]:
    """Adresse (minuscules) → accès (None pour la maîtrise d'œuvre). Jamais l'auteur de l'action."""
    resultat: dict[str, Acces | None] = {}
    document = evenement.document
    auteur = (evenement.utilisateur.email or "").lower() if evenement.utilisateur_id and evenement.utilisateur else ""
    if evenement.type not in EVENEMENTS_INTERNES:
        for acces in acces_actifs:
            if acces.frequence != frequence or acces.pk == evenement.acces_id or not acces.email:
                continue
            if document is not None and not concerne(acteur_intervenant(acces.intervenant), document):
                continue
            resultat.setdefault(acces.email.lower(), acces)
    # Maîtrise d'œuvre : tout de suite ce qui est à viser, le reste dans le récapitulatif du matin.
    if (frequence == Frequence.IMMEDIATE) == a_viser(evenement):
        for adresse in espace.liste_emails_moe():
            if adresse.lower() != auteur:
                resultat.setdefault(adresse.lower(), None)
    return resultat


def acces_destinataires(espace: EspaceChantier) -> list[Acces]:
    return list(Acces.objects.filter(intervenant__espace=espace, actif=True, intervenant__actif=True).select_related("intervenant").prefetch_related("intervenant__lots"))


def messages_nouveautes(espace: EspaceChantier, evenements: list[Evenement], frequence: str = Frequence.IMMEDIATE) -> list[tuple[EmailMessage, list[Evenement], Acces | None]]:
    acces_actifs = acces_destinataires(espace)
    par_adresse: dict[str, list[Evenement]] = defaultdict(list)
    qui: dict[str, Acces | None] = {}
    for evenement in evenements:
        for adresse, acces in destinataires(espace, evenement, acces_actifs, frequence).items():
            par_adresse[adresse].append(evenement)
            qui[adresse] = acces
    projet = espace.projet
    resultat = []
    for adresse, liste in par_adresse.items():
        moe = qui[adresse] is None
        quotidien = frequence == Frequence.QUOTIDIENNE
        lots = {e.document.lot.code for e in liste if e.document is not None and e.document.lot_id}
        prefixe = f"Lot {lots.pop()} : " if len(lots) == 1 and all(e.document is not None and e.document.lot_id for e in liste) else ""
        if quotidien:
            sujet = "récapitulatif du chantier"
        elif moe and all(a_viser(e) for e in liste):
            sujet = f"{len(liste)} document(s) à viser ou avis reçus"
        else:
            sujet = f"{len(liste)} nouveautés" if len(liste) > 1 else liste[0].get_type_display().lower()
        objet = f"[{projet.nom}] {prefixe}{sujet}"
        lignes = [f"{'Nouveautés des dernières 24 heures' if quotidien else 'Nouveautés'} sur l'espace documentaire du chantier « {projet.nom} » :", "", *[ligne_evenement(e) for e in liste]]
        documents = {e.document_id for e in liste if e.document_id}
        resultat.append((_message(projet, adresse, objet, lignes, moe, documents.pop() if len(documents) == 1 else None), liste, qui[adresse]))
    return resultat


def envoyer(paquets: list[tuple[EmailMessage, list[Evenement], Acces | None]]) -> int:
    """Envoie et enregistre chaque courriel (preuve de diffusion, erreurs comprises)."""
    if not paquets:
        return 0
    import time

    envoyes = 0
    with get_connection(fail_silently=False) as connexion:
        for rang, (message, evenements, acces) in enumerate(paquets):
            if rang and rang % MESSAGES_PAR_MINUTE == 0 and not settings.TESTS:
                time.sleep(60)  # débit limité : la messagerie du cabinet ne bloque pas l'envoi
            erreur, maintenant = "", timezone.now()
            try:
                envoyes += connexion.send_messages([message])
            except Exception as exc:  # noqa: BLE001 - un destinataire refusé ne bloque pas les autres
                erreur = f"{exc.__class__.__name__} : {exc}"[:300]
            Notification.objects.bulk_create([
                Notification(evenement=e, adresse=message.to[0], acces=acces, envoyee_le=None if erreur else maintenant, erreur=erreur)
                for e in evenements
            ])
    return envoyes


def message_recepisse(version: Version) -> EmailMessage | None:
    acces = version.deposee_par_acces
    if acces is None or not acces.email:
        return None
    document = version.document
    projet = document.espace.projet
    depose = timezone.localtime(version.deposee_le)
    lignes = [
        f"Nous accusons réception de votre dépôt sur l'espace documentaire du chantier « {projet.nom} » :", "",
        f"- Document : {document.reference} – {document.titre}" + (f" (n° {document.reference_emetteur})" if document.reference_emetteur else ""),
        f"- Indice : {version.indice}" + (f" – {version.objet}" if version.objet else ""),
        f"- {_lieu(document)}, {document.get_categorie_display().lower()}",
        f"- Fichier : {version.nom_original} ({version.taille} octets), empreinte SHA-256 {version.empreinte}",
        f"- Reçu le {depose:%d/%m/%Y à %H:%M}, déposé par {version.deposee_par_nom}",
    ]
    if version.diffusion == Diffusion.POUR_VISA and version.echeance_visa:
        lignes.append(f"- Soumis au visa de la maîtrise d'œuvre : réponse au plus tard le {version.echeance_visa:%d/%m/%Y}")
    lignes += ["", "Ce récépissé fait foi de la date de réception du document."]
    return _message(projet, acces.email, f"[{projet.nom}] Récépissé de dépôt – {document.reference} indice {version.indice}", lignes, False, document.pk)


def messages_quotidiens(espace: EspaceChantier) -> list[EmailMessage]:
    """Relances du matin : visas dus ou en retard (MOE), ordres de service non lus (entreprises)."""
    projet = espace.projet
    aujourd_hui = timezone.localdate()
    messages = []
    attente = list(
        Version.objects.filter(document__espace=espace, document__annule=False, diffusion=Diffusion.POUR_VISA, visa=StatutVisa.EN_ATTENTE,
                               echeance_visa__lte=aujourd_hui + datetime.timedelta(days=3))
        .select_related("document__lot").order_by("echeance_visa")
    )
    if attente and espace.liste_emails_moe():
        lignes = ["Documents en attente de visa dont l'échéance approche ou est dépassée :", ""]
        for v in attente:
            retard = (aujourd_hui - v.echeance_visa).days
            etat = f"EN RETARD de {retard} jour(s)" if retard > 0 else ("échéance aujourd'hui" if retard == 0 else f"échéance le {v.echeance_visa:%d/%m/%Y}")
            lignes.append(f"- {_lieu(v.document)} – {v.document.reference} indice {v.indice} – {v.document.titre} ({v.deposee_par_nom}) : {etat}")
        for adresse in espace.liste_emails_moe():
            messages.append(_message(projet, adresse, f"[{projet.nom}] Visas à rendre", lignes, True))
    lus = set(AccuseLecture.objects.filter(version__document__espace=espace).values_list("version_id", "intervenant_id"))
    for intervenant in espace.intervenants.filter(actif=True, profil="ENTREPRISE").prefetch_related("lots", "acces"):
        adresses = [a.email for a in intervenant.acces.all() if a.actif and a.email]
        if not adresses:
            continue
        lots = set(intervenant.lots.values_list("pk", flat=True))
        a_lire = [
            v for v in Version.objects.filter(document__espace=espace, document__annule=False, document__categorie__in=["OS", "AVT"], document__lot_id__in=lots)
            .select_related("document__lot")
            if (v.pk, intervenant.pk) not in lus
        ]
        if a_lire:
            lignes = ["Les documents suivants attendent votre accusé de lecture (bouton « J'ai pris connaissance ») :", ""]
            lignes += [f"- {_lieu(v.document)} – {v.document.reference} indice {v.indice} – {v.document.titre}, diffusé le {timezone.localtime(v.deposee_le):%d/%m/%Y}" for v in a_lire]
            for adresse in adresses:
                messages.append(_message(projet, adresse, f"[{projet.nom}] Ordres de service à lire", lignes, False))
    return messages
