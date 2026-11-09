"""Messages et envois du DCE.

Marché public : le DCE complet est transmis au maître d'ouvrage, qui le publie sur son profil
d'acheteur ; les entreprises peuvent être invitées à le consulter sur la plateforme.
Marché privé : chaque entreprise reçoit directement un dossier limité à ses lots.
"""
from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from projets.champs import champs_du_projet
from projets.models import LotProjet, Projet

from .models import DossierDCE, Envoi, StatutEnvoi

REPERE_ENTREPRISE = "[entreprise]"
REPERE_LOTS = "[lots]"


def _valeur(champs, cle: str, defaut: str = "[à compléter]") -> str:
    champ = champs.get(cle)
    return champ.apercu if champ and champ.renseigne and champ.apercu else defaut


def message_moa(projet: Projet, indice: str) -> tuple[str, str]:
    champs = champs_du_projet(projet)
    objet = f"{projet.nom} – DCE indice {indice}"
    texte = f"""Madame, Monsieur,

Veuillez trouver ci-joint le dossier de consultation des entreprises (DCE, indice {indice}) de l'opération « {projet.nom} », en vue de sa publication sur votre profil d'acheteur.

Le dossier comprend {_valeur(champs, "nombre_lots", "les")} lots ; le bordereau des pièces, placé en tête du dossier, en donne la liste complète.

Date limite de remise des offres proposée : {_valeur(champs, "date_limite_offres")}.

Nous restons à votre disposition pour toute précision.

Bien cordialement,

{projet.maitre_oeuvre or "La maîtrise d'œuvre"}"""
    return objet, texte


def message_entreprise(projet: Projet) -> tuple[str, str]:
    champs = champs_du_projet(projet)
    objet = f"Consultation – {projet.nom} – {REPERE_LOTS}"
    if projet.type_marche == "PUBLIC":
        corps = f"""Madame, Monsieur,

Le dossier de consultation de l'opération « {projet.nom} » ({_valeur(champs, "maitre_ouvrage")}) est en ligne sur le profil d'acheteur : {_valeur(champs, "profil_acheteur")}.

Votre entreprise ({REPERE_ENTREPRISE}) est invitée à le consulter et à remettre une offre pour : {REPERE_LOTS}.

Les offres sont à déposer exclusivement sur la plateforme, au plus tard le {_valeur(champs, "date_limite_offres")}.

Bien cordialement,

{projet.maitre_oeuvre or "La maîtrise d'œuvre"}"""
    else:
        corps = f"""Madame, Monsieur,

Pour le compte de {_valeur(champs, "maitre_ouvrage")}, nous consultons votre entreprise ({REPERE_ENTREPRISE}) pour l'opération « {projet.nom} », {REPERE_LOTS}.

Vous trouverez ci-joint le dossier de consultation (pièces écrites, plans et décomposition du prix à compléter).

Merci de nous faire parvenir votre offre au plus tard le {_valeur(champs, "date_limite_offres")}. Pour toute question : {_valeur(champs, "contact_consultation", projet.maitre_oeuvre or "la maîtrise d'œuvre")}.

Bien cordialement,

{projet.maitre_oeuvre or "La maîtrise d'œuvre"}"""
    return objet, corps


def personnaliser(texte: str, entreprise, lots: list[LotProjet]) -> str:
    libelle_lots = ", ".join(f"lot {l.code} {l.intitule}" for l in lots) or "les lots concernés"
    return texte.replace(REPERE_ENTREPRISE, entreprise.raison_sociale if entreprise else "").replace(REPERE_LOTS, libelle_lots)


def envoyer_courriel(envoi: Envoi, dossier: DossierDCE | None) -> None:
    """Envoie le courriel (dossier joint s'il n'est pas trop lourd) ; l'état est enregistré dans `envoi`."""
    message = envoi.message
    piece_jointe = False
    if dossier is not None and dossier.fichier:
        limite = settings.EMAIL_PIECE_JOINTE_MAX_MO * 1024 * 1024
        if dossier.taille <= limite:
            piece_jointe = True
        else:
            envoi.statut = StatutEnvoi.A_ENVOYER
            envoi.erreur = (
                f"Dossier trop lourd pour un e-mail ({dossier.taille / 1048576:.0f} Mo, maximum {settings.EMAIL_PIECE_JOINTE_MAX_MO} Mo) : "
                "téléchargez-le et transmettez-le par un service de transfert (FranceTransfert, WeTransfer…)."
            )
            envoi.save(update_fields=["statut", "erreur"])
            return
    courriel = EmailMessage(
        subject=envoi.objet,
        body=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[d.strip() for d in envoi.destinataires.split(",") if d.strip()],
        reply_to=[settings.DEFAULT_FROM_EMAIL] if settings.DEFAULT_FROM_EMAIL else None,
    )
    if piece_jointe:
        with dossier.fichier.open("rb") as flux:
            courriel.attach(dossier.nom or "DCE.zip", flux.read(), "application/zip")
    try:
        courriel.send(fail_silently=False)
    except Exception as erreur:  # noqa: BLE001 - serveur injoignable, identifiants refusés…
        envoi.statut = StatutEnvoi.ERREUR
        envoi.erreur = f"Envoi impossible ({erreur.__class__.__name__} : {str(erreur)[:200]}). Vérifiez les réglages de messagerie."
        envoi.save(update_fields=["statut", "erreur"])
        return
    envoi.statut, envoi.piece_jointe, envoi.envoye_le, envoi.erreur = StatutEnvoi.ENVOYE, piece_jointe, timezone.now(), ""
    envoi.save(update_fields=["statut", "piece_jointe", "envoye_le", "erreur"])
