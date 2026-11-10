"""Sauvegarde de chaque nuit : déroulé, rotation, état affiché dans l'application, courriel d'échec.

Déroulé (une seule sauvegarde à la fois) :
  a) pg_dump de la base vers base/AAAA-MM-JJ_HHMM.dump (écrit dans un .partiel puis renommé) ;
  b) restauration d'essai dans une base temporaire et comparaison des lignes de chaque table ;
  c) copie du .env (la clé DJANGO_SECRET_KEY rend les codes d'accès de la GED valides après restauration) ;
  d) fichiers sur le PC : miroir des fichiers et des archives (suppression différée de 30 jours) ;
  e) rotation : SAUVEGARDE_JOURS sauvegardes quotidiennes et SAUVEGARDE_MOIS mensuelles ;
  f) échec : courriel aux administrateurs (si la messagerie est réglée).
"""
from __future__ import annotations

import contextlib
import datetime
import logging
import os
import re
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone

from . import postgres
from .miroir import DELAI_SUPPRESSION, SUFFIXE_PARTIEL, miroir
from .models import Sauvegarde, StatutSauvegarde
from .postgres import ErreurSauvegarde

logger = logging.getLogger(__name__)

DUREE_MAX = datetime.timedelta(hours=6)  # au-delà, la tâche a été tuée : sauvegarde interrompue
DELAI_ALERTE = datetime.timedelta(hours=36)
INTERROMPUE = "Sauvegarde interrompue (arrêt du PC ou de l’application) : relancez-la ou attendez celle de la nuit."
MOTIF_COPIE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(?:-(\d+))?\.dump$")
CLE_VERROU = 7_041_946  # verrou consultatif PostgreSQL propre à la sauvegarde
LISEZ_MOI = """D’Aplomb — sauvegardes
=====================

Ce dossier est rempli automatiquement chaque nuit par D’Aplomb. Ne modifiez pas son contenu.

base\\            copies de la base de données (AAAA-MM-JJ_HHMM.dump) : les {jours} derniers jours
                  et la première copie de chacun des {mois} derniers mois
configuration\\   copie du fichier .env de l’application : clé des codes d’accès de la GED et mots de
                  passe. CONFIDENTIEL. Les versions remplacées sont dans configuration\\historique.
fichiers\\        copie des fichiers de l’application et des archives de fin de chantier, quand ils
archives\\        sont rangés sur le PC (un fichier supprimé y reste encore 30 jours)
manifestes\\      suivi des fichiers supprimés (ne pas modifier)

Restaurer après une panne
-------------------------
1. Installez D’Aplomb sur le PC. AVANT de lancer installer.ps1, copiez configuration\\.env à la
   place du fichier .env du dossier de l’application : sans cette clé, les codes d’accès des
   entreprises à la GED ne fonctionnent plus.
2. Si les fichiers étaient sur le PC, recopiez fichiers\\ et archives\\ dans le dossier donnees\\ de
   l’application (ou utilisez l’option --avec-fichiers ci-dessous).
3. Lancez installer.ps1, puis, dans le dossier de l’application :
     docker compose exec worker python manage.py restaurer AAAA-MM-JJ_HHMM.dump --confirmer
   La base actuelle est d’abord copiée dans base\\avant-restauration_….dump.
"""


def dossier() -> Path:
    return Path(settings.DOSSIER_SAUVEGARDES)


# --- Verrou et sauvegardes interrompues ---------------------------------------------------------------

@contextlib.contextmanager
def verrou():
    """Une seule sauvegarde (ou restauration) à la fois, quel que soit le processus qui la lance.

    Avec PostgreSQL : verrou consultatif, libéré automatiquement si le processus meurt.
    """
    if "postgresql" in settings.DATABASES["default"]["ENGINE"]:
        with postgres.connexion(postgres.parametres()) as liaison:
            liaison.autocommit = True
            obtenu = bool(liaison.execute("SELECT pg_try_advisory_lock(%s)", (CLE_VERROU,)).fetchone()[0])
            try:
                yield obtenu
            finally:
                if obtenu:
                    with contextlib.suppress(Exception):
                        liaison.execute("SELECT pg_advisory_unlock(%s)", (CLE_VERROU,))
        return
    cle = "sauvegardes:verrou"
    obtenu = cache.add(cle, "1", int(DUREE_MAX.total_seconds()))
    try:
        yield obtenu
    finally:
        if obtenu:
            cache.delete(cle)


def liberer_interrompues(age_minimum: datetime.timedelta | None = None) -> int:
    """Sauvegardes restées « en cours » alors que leur tâche est perdue : passées en échec.

    Sans âge minimum : toutes (démarrage du worker, aucune ne peut tourner).
    """
    sauvegardes = Sauvegarde.objects.filter(statut=StatutSauvegarde.EN_COURS)
    if age_minimum is not None:
        sauvegardes = sauvegardes.filter(debut__lt=timezone.now() - age_minimum)
    return sauvegardes.update(statut=StatutSauvegarde.ECHEC, fin=timezone.now(), message=INTERROMPUE)


def _preparer(declenchee_par: str, sauvegarde_id: int | None) -> Sauvegarde | None:
    maintenant = timezone.now()
    if sauvegarde_id is not None:  # demandée depuis l'application
        sauvegarde = Sauvegarde.objects.filter(pk=sauvegarde_id).first()
        if sauvegarde is None or sauvegarde.statut == StatutSauvegarde.REUSSIE:
            return None
        if sauvegarde.statut == StatutSauvegarde.ECHEC and sauvegarde.message != INTERROMPUE:
            return None
        # « Interrompue » au redémarrage du worker alors qu'elle attendait son tour : elle est faite maintenant.
        sauvegarde.statut, sauvegarde.debut, sauvegarde.fin, sauvegarde.message = StatutSauvegarde.EN_COURS, maintenant, None, ""
        sauvegarde.save(update_fields=["statut", "debut", "fin", "message"])
        return sauvegarde
    liberer_interrompues(DUREE_MAX)
    if Sauvegarde.objects.filter(statut=StatutSauvegarde.EN_COURS).exists():
        return None  # une demande de l'application attend son tour : elle suffit
    return Sauvegarde.objects.create(debut=maintenant, declenchee_par=declenchee_par)


def lancer(declenchee_par: str, sauvegarde_id: int | None = None) -> Sauvegarde | None:
    """Fait une sauvegarde complète ; None si une autre est en cours (ou si la demande est déjà traitée)."""
    with verrou() as obtenu:
        if not obtenu:
            if sauvegarde_id is not None:
                Sauvegarde.objects.filter(pk=sauvegarde_id, statut=StatutSauvegarde.EN_COURS).update(
                    statut=StatutSauvegarde.ECHEC, fin=timezone.now(), message="Une autre sauvegarde était déjà en cours.")
            return None
        sauvegarde = _preparer(declenchee_par, sauvegarde_id)
        if sauvegarde is not None:
            realiser(sauvegarde)
        return sauvegarde


# --- Étapes ---------------------------------------------------------------------------------------------

def taille_lisible(octets: int) -> str:
    valeur = float(octets)
    for unite in ("octets", "Ko", "Mo", "Go"):
        if valeur < 1024 or unite == "Go":
            break
        valeur /= 1024
    texte = f"{valeur:.0f}" if unite == "octets" or valeur >= 100 else f"{valeur:.1f}".replace(".", ",")
    return f"{texte} {unite}"


def _nombre(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _ecrire_atomique(cible: Path, contenu: bytes) -> None:
    partiel = cible.with_name(cible.name + SUFFIXE_PARTIEL)
    partiel.write_bytes(contenu)
    os.replace(partiel, cible)


def _ecrire_lisez_moi(racine: Path) -> None:
    contenu = LISEZ_MOI.format(jours=settings.SAUVEGARDE_JOURS, mois=settings.SAUVEGARDE_MOIS).replace("\n", "\r\n").encode("utf-8-sig")
    cible = racine / "LISEZ-MOI.txt"
    with contextlib.suppress(OSError):
        if cible.read_bytes() == contenu:
            return
    _ecrire_atomique(cible, contenu)


def _nom_copie(dossier_base: Path, debut: datetime.datetime) -> Path:
    nom = f"{timezone.localtime(debut):%Y-%m-%d_%H%M}"
    cible, rang = dossier_base / f"{nom}.dump", 2
    while cible.exists():  # deux sauvegardes dans la même minute
        cible, rang = dossier_base / f"{nom}-{rang}.dump", rang + 1
    return cible


def sauvegarder_base(racine: Path, debut: datetime.datetime) -> tuple[Path, dict[str, int]]:
    """Étape a : copie de la base, écrite sous un nom provisoire puis renommée une fois complète."""
    p = postgres.parametres()
    dossier_base = racine / "base"
    dossier_base.mkdir(parents=True, exist_ok=True)
    cible = _nom_copie(dossier_base, debut)
    partiel = cible.with_name(cible.name + SUFFIXE_PARTIEL)
    try:
        comptes = postgres.exporter(partiel, p)
        if not partiel.exists() or partiel.stat().st_size == 0:
            raise ErreurSauvegarde("pg_dump n’a rien écrit.")
        os.replace(partiel, cible)
    except BaseException:
        with contextlib.suppress(OSError):
            partiel.unlink()
        raise
    return cible, comptes


def copier_configuration(racine: Path, maintenant: datetime.datetime) -> str:
    """Étape c : copie du .env ; une version remplacée est gardée (un .env régénéré par erreur
    n'efface pas l'ancienne clé des codes d'accès de la GED)."""
    source = Path(settings.FICHIER_CONFIGURATION)
    try:
        contenu = source.read_bytes()
    except FileNotFoundError as exc:
        raise ErreurSauvegarde(f"fichier {source} introuvable : la clé des codes d’accès de la GED n’est pas sauvegardée.") from exc
    except OSError as exc:
        raise ErreurSauvegarde(f"fichier {source} illisible ({exc.strerror or exc}).") from exc
    if b"DJANGO_SECRET_KEY" not in contenu:
        raise ErreurSauvegarde(f"le fichier {source} ne contient pas DJANGO_SECRET_KEY : ce n’est pas le .env de l’application.")
    destination = racine / "configuration"
    destination.mkdir(parents=True, exist_ok=True)
    cible = destination / ".env"
    try:
        ancien = cible.read_bytes()
    except FileNotFoundError:
        ancien = None
    if ancien == contenu:
        return "Configuration (.env) déjà à jour."
    if ancien is not None:
        historique = destination / "historique"
        historique.mkdir(exist_ok=True)
        _ecrire_atomique(historique / f"remplace-le-{timezone.localtime(maintenant):%Y-%m-%d_%H%M}.env", ancien)
    _ecrire_atomique(cible, contenu)
    return "Configuration (.env) copiée."


def _contient(parent: Path, enfant: Path) -> bool:
    try:
        enfant.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def copier_fichiers(racine: Path, maintenant: datetime.datetime) -> tuple[int, list[str], list[str]]:
    """Étape d : miroir des fichiers et des archives (seulement quand ils sont sur le PC).

    Renvoie (fichiers copiés, compte rendu, erreurs).
    """
    copies, compte_rendu, erreurs = 0, [], []
    for nom, source in (("fichiers", Path(settings.MEDIA_ROOT)), ("archives", Path(settings.DOSSIER_ARCHIVES))):
        autres = (Path(settings.DOSSIER_ARCHIVES), racine) if nom == "fichiers" else (racine,)
        exclus = tuple(chemin for chemin in autres if _contient(source, chemin))
        bilan = miroir(source, racine / nom, maintenant, manifeste=racine / "manifestes" / f"{nom}.json", exclus=exclus)
        copies += bilan.copies
        texte = f"{nom.capitalize()} : {_nombre(bilan.copies)} copié(s)"
        if bilan.copies:
            texte += f" ({taille_lisible(bilan.octets)})"
        if bilan.en_attente:
            texte += f", {_nombre(bilan.en_attente)} supprimé(s) de l’application gardé(s) {DELAI_SUPPRESSION.days} jours"
        if bilan.supprimes:
            texte += f", {_nombre(bilan.supprimes)} effacé(s) de la sauvegarde"
        if bilan.suppressions_suspendues:
            texte += f" (aucune suppression : {bilan.suppressions_suspendues})"
        compte_rendu.append(texte + ".")
        if bilan.erreurs:
            exemples = " ; ".join(bilan.erreurs[:3])
            erreurs.append(f"{nom.capitalize()} : {_nombre(len(bilan.erreurs))} fichier(s) non copié(s) ({exemples}).")
    return copies, compte_rendu, erreurs


def rotation(dossier_base: Path, jours: int, mois: int, proteges: set[str] = frozenset()) -> list[str]:
    """Étape e : garde la dernière copie de chacun des `jours` derniers jours sauvegardés et la première
    de chacun des `mois` derniers mois ; `proteges` (noms de fichiers) ne sont jamais effacés.

    Les fichiers qui ne suivent pas le nom AAAA-MM-JJ_HHMM.dump (copie avant restauration…) sont ignorés.
    """
    copies = []
    for chemin in dossier_base.iterdir():
        correspondance = MOTIF_COPIE.match(chemin.name)
        if correspondance and chemin.is_file():
            moment = tuple(int(correspondance[i]) for i in range(1, 6)) + (int(correspondance[6] or 1),)
            copies.append((moment, chemin))
    copies.sort()
    garder: set[Path] = set()
    par_jour: dict[tuple, Path] = {}
    par_mois: dict[tuple, Path] = {}
    for moment, chemin in copies:
        par_jour[moment[:3]] = chemin  # la plus récente du jour
        par_mois.setdefault(moment[:2], chemin)  # la première du mois
    if jours > 0:
        garder.update(par_jour[jour] for jour in sorted(par_jour)[-jours:])
    if mois > 0:
        garder.update(par_mois[m] for m in sorted(par_mois)[-mois:])
    effacees = []
    for _moment, chemin in copies:
        if chemin in garder or chemin.name in proteges:
            continue
        chemin.unlink(missing_ok=True)
        effacees.append(chemin.name)
    for partiel in dossier_base.glob(f"*{SUFFIXE_PARTIEL}"):  # copies interrompues (le verrou est tenu)
        with contextlib.suppress(OSError):
            partiel.unlink()
    return effacees


def _derniere_verifiee() -> set[str]:
    sauvegarde = Sauvegarde.objects.filter(statut=StatutSauvegarde.REUSSIE, verifiee=True).exclude(fichier="").first()
    return {Path(sauvegarde.fichier).name} if sauvegarde else set()


def _etape(libelle: str, erreurs: list[str], fonction, *arguments):
    try:
        return fonction(*arguments)
    except SoftTimeLimitExceeded:
        raise
    except ErreurSauvegarde as exc:
        texte = str(exc).rstrip()
        erreurs.append(f"{libelle} : {texte}" + ("" if texte.endswith((".", "…", "!", "?", ")")) else "."))
    except OSError as exc:
        erreurs.append(f"{libelle} : {exc.strerror or exc}" + (f" ({exc.filename})" if exc.filename else "") + ".")
    except Exception as exc:  # noqa: BLE001 - l'étape suivante est tentée quand même
        logger.exception("Sauvegarde : étape « %s » en erreur", libelle)
        erreurs.append(f"{libelle} : erreur inattendue ({exc.__class__.__name__} : {exc}).")
    return None


def _preparer_dossier(racine: Path) -> None:
    try:
        racine.mkdir(parents=True, exist_ok=True)
        _ecrire_lisez_moi(racine)
    except OSError as exc:
        raise ErreurSauvegarde(f"{destination_affichee()} inaccessible ({exc.strerror or exc}).") from exc


def _derouler(sauvegarde: Sauvegarde, erreurs: list[str], compte_rendu: list[str]) -> None:
    racine, maintenant = dossier(), timezone.now()
    _etape("Dossier des sauvegardes", erreurs, _preparer_dossier, racine)
    if erreurs:
        return  # partage du serveur ou disque injoignable : rien d'autre n'est possible
    # a) et b) : copie de la base, puis restauration d'essai.
    resultat = _etape("Base de données", erreurs, sauvegarder_base, racine, sauvegarde.debut)
    if resultat is not None:
        copie, comptes = resultat
        sauvegarde.fichier = copie.relative_to(racine).as_posix()
        sauvegarde.taille = copie.stat().st_size
        sauvegarde.save(update_fields=["fichier", "taille"])
        essai: list[str] = []
        verification = _etape("Restauration d’essai", essai, postgres.verifier, copie, postgres.parametres(), comptes)
        if verification is not None:
            sauvegarde.verifiee = True
            tables, lignes = verification
            compte_rendu.append(f"Base : {taille_lisible(sauvegarde.taille)}, vérifiée par une restauration d’essai "
                                f"({_nombre(tables)} tables, {_nombre(lignes)} lignes).")
        else:
            compte_rendu.append(f"Base : {taille_lisible(sauvegarde.taille)}, NON VÉRIFIÉE. " + " ".join(essai))
    # c) configuration.
    texte = _etape("Configuration", erreurs, copier_configuration, racine, maintenant)
    if texte:
        compte_rendu.append(texte)
    # d) fichiers et archives, seulement quand ils sont sur le PC.
    if settings.STOCKAGE_SERVEUR:
        compte_rendu.append("Fichiers et archives : déjà sur le serveur de l’agence, pas de copie.")
    else:
        bilan = _etape("Fichiers", erreurs, copier_fichiers, racine, maintenant)
        if bilan is not None:
            sauvegarde.fichiers_copies, textes, erreurs_fichiers = bilan
            compte_rendu.extend(textes)
            erreurs.extend(erreurs_fichiers)
    # e) rotation, seulement après une copie réussie (un échec n'efface jamais les anciennes).
    if resultat is not None:
        avertissements: list[str] = []
        effacees = _etape("Rotation", avertissements, rotation, racine / "base", settings.SAUVEGARDE_JOURS,
                          settings.SAUVEGARDE_MOIS, _derniere_verifiee() | {resultat[0].name})
        if effacees:
            compte_rendu.append(f"{len(effacees)} ancienne(s) copie(s) de la base effacée(s).")
        compte_rendu.extend(avertissements)


def realiser(sauvegarde: Sauvegarde) -> None:
    """Exécute les étapes et enregistre le compte rendu ; f) prévient les administrateurs en cas d'échec."""
    erreurs: list[str] = []
    compte_rendu: list[str] = []
    try:
        _derouler(sauvegarde, erreurs, compte_rendu)
    except SoftTimeLimitExceeded:
        erreurs.append(f"Durée maximale dépassée ({int(DUREE_MAX.total_seconds() // 3600)} heures) : sauvegarde arrêtée.")
    except Exception as exc:  # noqa: BLE001 - la sauvegarde ne doit pas rester « en cours »
        logger.exception("Sauvegarde %s interrompue par une erreur", sauvegarde.pk)
        erreurs.append(f"Erreur inattendue ({exc.__class__.__name__} : {exc}).")
    sauvegarde.statut = StatutSauvegarde.ECHEC if erreurs else StatutSauvegarde.REUSSIE
    sauvegarde.fin = timezone.now()
    sauvegarde.message = " ".join(erreurs + compte_rendu)[:4000]
    sauvegarde.save()
    if sauvegarde.statut == StatutSauvegarde.ECHEC or not sauvegarde.verifiee:
        logger.error("Sauvegarde %s : %s", sauvegarde.pk, sauvegarde.message)
        courriel_echec(sauvegarde)
    else:
        logger.info("Sauvegarde %s réussie : %s", sauvegarde.pk, sauvegarde.message)


# --- État affiché et alerte ----------------------------------------------------------------------------

def destination_affichee() -> str:
    if settings.STOCKAGE_SERVEUR:
        partage = settings.SERVEUR_CHEMIN_AFFICHE
        if not partage and settings.SERVEUR_ADRESSE and settings.SERVEUR_PARTAGE:
            partage = "\\\\" + settings.SERVEUR_ADRESSE + "\\" + settings.SERVEUR_PARTAGE.replace("/", "\\")
        if partage:
            return partage.rstrip("\\/") + "\\sauvegardes"
    return settings.DOSSIER_SAUVEGARDES_AFFICHE or "donnees\\sauvegardes"


def sur_le_meme_disque() -> bool:
    """Sauvegardes sur le disque de l'application (dossier par défaut, chemin relatif ou disque C:, celui
    de Docker et donc de la base) : une panne du PC les emporterait avec le reste."""
    if settings.STOCKAGE_SERVEUR:
        return False
    chemin = settings.DOSSIER_SAUVEGARDES_PC.strip().strip('"')
    if not chemin:
        return True
    if chemin.startswith(("\\\\", "//")):
        return False  # partage réseau
    lecteur = re.match(r"^([A-Za-z]):", chemin)
    return lecteur is None or lecteur[1].upper() == "C"


def _date(moment: datetime.datetime) -> str:
    return f"{timezone.localtime(moment):%d/%m/%Y à %H:%M}"


def _premiere_partie(message: str, longueur: int = 300) -> str:
    message = message.strip()
    return message if len(message) <= longueur else message[: longueur - 1].rstrip() + "…"


def alerte(derniere_terminee: Sauvegarde | None, derniere_reussie: Sauvegarde | None, maintenant: datetime.datetime) -> str:
    messages = []
    if derniere_reussie is None:
        messages.append("Aucune sauvegarde n’a encore réussi : vos données ne sont pas protégées.")
    if derniere_terminee is not None and derniere_terminee.statut == StatutSauvegarde.ECHEC:
        messages.append(f"La dernière sauvegarde (le {_date(derniere_terminee.debut)}) a échoué : {_premiere_partie(derniere_terminee.message)}")
    if derniere_reussie is not None:
        fin = derniere_reussie.fin or derniere_reussie.debut
        if maintenant - fin > DELAI_ALERTE:
            messages.append(f"La dernière sauvegarde réussie date du {_date(fin)}, il y a plus de 36 heures : "
                            "le PC ou l’application étaient-ils arrêtés la nuit ?")
        if derniere_terminee is not None and derniere_terminee.pk == derniere_reussie.pk and not derniere_reussie.verifiee:
            messages.append("La dernière sauvegarde n’a pas pu être vérifiée par une restauration d’essai.")
    if sur_le_meme_disque():
        messages.append("Les sauvegardes sont sur le même disque que l’application : une panne du PC les emporterait aussi. "
                        "Enregistrez-les sur le serveur de l’agence ou sur un disque externe.")
    return " ".join(messages)


def etat() -> dict:
    liberer_interrompues(DUREE_MAX)
    maintenant = timezone.now()
    derniere = Sauvegarde.objects.first()
    terminee = Sauvegarde.objects.exclude(statut=StatutSauvegarde.EN_COURS).first()
    reussie = Sauvegarde.objects.filter(statut=StatutSauvegarde.REUSSIE).first()
    heure, minute = settings.SAUVEGARDE_HEURE
    return {
        "derniere": None if derniere is None else {
            "debut": derniere.debut, "fin": derniere.fin, "statut": derniere.statut, "statut_libelle": derniere.get_statut_display(),
            "taille": derniere.taille, "verifiee": derniere.verifiee, "message": derniere.message,
        },
        "derniere_reussie": None if reussie is None else {"fin": reussie.fin, "taille": reussie.taille, "verifiee": reussie.verifiee},
        "en_cours": Sauvegarde.objects.filter(statut=StatutSauvegarde.EN_COURS).exists(),
        "destination": destination_affichee(),
        "stockage_serveur": bool(settings.STOCKAGE_SERVEUR),
        "alerte": alerte(terminee, reussie, maintenant),
        "heure": f"{heure} h {minute:02d}",
    }


# --- Courriel d'échec ----------------------------------------------------------------------------------

def destinataires_alerte() -> list[str]:
    from comptes.models import Utilisateur

    adresses = (Utilisateur.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(role=Utilisateur.Role.ADMINISTRATEUR))
                .exclude(email="").values_list("email", flat=True))
    return sorted({adresse.strip() for adresse in adresses if adresse.strip()})


def courriel_echec(sauvegarde: Sauvegarde) -> int:
    """Prévient les administrateurs (échec, ou copie de la base non vérifiée). Jamais bloquant."""
    if not settings.EMAIL_ACTIF:
        return 0
    try:
        destinataires = destinataires_alerte()
        if not destinataires:
            return 0
        echec = sauvegarde.statut == StatutSauvegarde.ECHEC
        sujet = "D’Aplomb : la sauvegarde a échoué" if echec else "D’Aplomb : sauvegarde non vérifiée"
        if settings.STOCKAGE_SERVEUR:
            conseil = ("Vérifiez que le serveur de l’agence est allumé, joignable depuis le PC de l’application, et qu’il lui reste "
                       "de la place.")
        else:
            conseil = "Vérifiez que le dossier des sauvegardes est accessible et qu’il reste de la place sur son disque."
        corps = "\n".join([
            "Bonjour,",
            "",
            f"La sauvegarde de D’Aplomb lancée le {_date(sauvegarde.debut)} "
            + ("a échoué." if echec else "a été faite, mais la restauration d’essai de la base n’a pas réussi."),
            "",
            f"Compte rendu : {sauvegarde.message}",
            "",
            f"Destination : {destination_affichee()}",
            "",
            "Vos données sont intactes dans l’application, mais elles ne sont plus protégées tant qu’une sauvegarde "
            f"complète n’a pas réussi. {conseil} Relancez ensuite la sauvegarde depuis l’application, avec un compte "
            f"administrateur : {settings.URL_APPLICATION}",
            "",
            "Message envoyé automatiquement par D’Aplomb.",
        ])
        return send_mail(sujet, corps, settings.DEFAULT_FROM_EMAIL, destinataires, fail_silently=False)
    except Exception:  # noqa: BLE001 - messagerie injoignable : l'alerte reste affichée dans l'application
        logger.exception("Courriel d'échec de la sauvegarde %s non envoyé", sauvegarde.pk)
        return 0
