"""Lecture isolée : un fichier reçu est analysé dans un processus séparé, plafonné en mémoire et en temps.

Les garde-fous statiques de lecture.py (bombes zip, pages géantes…) écartent les pièges connus. Ce processus
séparé arrête tous les autres, quel que soit le piège : un document qui épuiserait la mémoire, bouclerait sans
fin ou ferait planter une bibliothèque (pdfium, lxml, LibreOffice, Tesseract) tue au pire ce processus, jamais
le worker Celery ni le serveur web. Les plafonds valent aussi pour LibreOffice et Tesseract, qu'il lance.

Parent : executer_isole(cible, *args, **kwargs) lance « python -m bibliotheque.lecture_isolee » (et non
multiprocessing : les processus de Celery prefork sont « daemonic » et ne peuvent pas en créer), lui passe la
fonction à appeler et ses arguments dans un fichier pickle, puis relit le résultat dans un autre fichier.
Enfant : plafonne sa mémoire virtuelle (RLIMIT_AS) et son temps de calcul (RLIMIT_CPU), fait django.setup(),
appelle la fonction et écrit le résultat. Le parent l'arrête, avec tout son groupe de processus, au-delà du délai.
"""
from __future__ import annotations

import importlib
import logging
import os
import pickle
import resource
import select
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# Exceptions métier retransmises telles quelles au parent (même classe, même message).
EXCEPTIONS_TRANSMISES = {
    ("bibliotheque.lecture", "ErreurLecture"),
    ("bibliotheque.lecture", "FormatNonAnalyse"),
    ("entreprises.importation", "ImportImpossible"),
}
# Types que le résultat peut contenir (valeurs de cellules d'un classeur comprises) : rien d'autre n'est relu.
TYPES_RESULTAT = {
    ("bibliotheque.lecture", "ContenuDocument"),
    ("bibliotheque.lecture", "Bloc"),
    ("bibliotheque.lecture", "Tableau"),
    ("datetime", "datetime"),
    ("datetime", "date"),
    ("datetime", "time"),
    ("datetime", "timedelta"),
    ("datetime", "timezone"),
    ("decimal", "Decimal"),
    ("builtins", "complex"),
    ("builtins", "bytearray"),
}
CODE_MEMOIRE = 3  # code de sortie de l'enfant après une MemoryError (rien n'est écrit, la mémoire manque)
JOURNAL_GARDE = 4000  # fin de la sortie d'erreur de l'enfant gardée pour le journal (le reste est lu et oublié)
FICHIER_ECRIT_MAX = 1024 * 1024 * 1024  # taille d'un fichier écrit par l'enfant ou ses outils (RLIMIT_FSIZE)


class LimiteDepassee(Exception):
    """L'enfant a été arrêté : plafond de mémoire ou de temps atteint, tué par un signal, ou mort sans résultat."""


class ErreurEnfant(Exception):
    """Exception inattendue dans l'enfant (ni métier, ni limite) ; nom : sa classe d'origine."""

    def __init__(self, nom: str, message: str):
        super().__init__(f"{nom}: {message}")
        self.nom = nom


def _sockets_libreoffice() -> set[str]:
    """Sockets OSL_PIPE de LibreOffice, toujours créés dans /tmp (TMPDIR ne les déplace pas)."""
    import glob

    return set(glob.glob(f"/tmp/OSL_PIPE_{os.getuid()}_SingleOfficeIPC_*"))


def _retirer_sockets_orphelins(chemins: set[str], attente: float = 5.0) -> None:
    """Retire les sockets laissés par un LibreOffice tué, dès que plus personne n'y écoute : le noyau ne les
    ferme qu'à la fin effective du processus, un peu après le SIGKILL. Un socket qui répond encore au bout de
    l'attente (conversion lancée en même temps par une autre lecture) est gardé."""
    import contextlib
    import socket

    restants = set(chemins)
    limite = time.monotonic() + attente
    while restants:
        for chemin in sorted(restants):
            prise = socket.socket(socket.AF_UNIX)
            try:
                prise.connect(chemin)
            except ConnectionRefusedError:
                with contextlib.suppress(OSError):
                    os.unlink(chemin)
                restants.discard(chemin)
            except OSError:  # déjà retiré, ou pas à nous
                restants.discard(chemin)
            finally:
                prise.close()
        if not restants or time.monotonic() >= limite:
            return
        time.sleep(0.1)


def executer_isole(cible: str, *args, dossier: Path | None = None, memoire_mo: int | None = None,
                   delai: int | None = None, cpu: int | None = None, **kwargs):
    """Résultat de cible(*args, **kwargs), calculé dans un processus séparé et plafonné.

    cible : « module:fonction » (importée par l'enfant après django.setup()). dossier : où écrire les fichiers
    d'échange (dossier de travail de la lecture ; dossier temporaire du système sinon). memoire_mo et delai :
    LECTURE_MEMOIRE_MAX_MO et LECTURE_DELAI_MAX par défaut ; cpu (temps de calcul, secondes) : le délai par
    défaut. Lève l'exception métier de l'enfant telle quelle, LimiteDepassee si l'enfant a dépassé un plafond
    ou est mort, ErreurEnfant pour toute autre exception.
    """
    memoire_mo = settings.LECTURE_MEMOIRE_MAX_MO if memoire_mo is None else memoire_mo
    delai = settings.LECTURE_DELAI_MAX if delai is None else delai
    cpu = delai if cpu is None else cpu
    with tempfile.TemporaryDirectory(prefix="lecture-isolee-", dir=dossier) as echange:
        echange = Path(echange)
        requete, resultat = echange / "requete.pickle", echange / "resultat.pickle"
        with open(requete, "wb") as fichier:
            pickle.dump((cible, args, kwargs), fichier, protocol=pickle.HIGHEST_PROTOCOL)
        commande = [
            sys.executable, "-m", "bibliotheque.lecture_isolee",
            str(int(memoire_mo * 1024 * 1024)), str(int(cpu)), str(requete), str(resultat),
        ]
        debut = time.monotonic()
        journal = bytearray()
        sockets_avant = _sockets_libreoffice()
        # Groupe de processus propre : LibreOffice, Tesseract… sont arrêtés avec l'enfant. Sortie d'erreur lue
        # au fil de l'eau dans un tube, dont seule la fin est gardée : un fichier piégé qui ferait écrire des
        # avertissements sans fin ne remplit pas le disque.
        enfant = subprocess.Popen(
            commande, cwd=settings.BASE_DIR, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True, env={**os.environ, "DJANGO_SETTINGS_MODULE": os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings")},
        )
        try:
            termine = _attendre(enfant, delai, journal)
        finally:
            _arreter(enfant, journal)
            if enfant.returncode != 0:
                _retirer_sockets_orphelins(_sockets_libreoffice() - sockets_avant)
        duree = time.monotonic() - debut
        code = enfant.returncode
        if not termine:
            logger.warning("Lecture isolée %s arrêtée après %.0f s (délai de %s s).", cible, duree, delai)
            raise LimiteDepassee(f"délai de {delai} s dépassé")
        if code != 0 or not resultat.exists():
            if code < 0:
                raison = f"tuée par le signal {_nom_signal(-code)}"  # SIGKILL (mémoire du conteneur), SIGXCPU, SIGSEGV…
            elif code == CODE_MEMOIRE:
                raison = "mémoire épuisée (MemoryError)"
            else:
                raison = f"arrêtée (code {code})"
            # Code positif inattendu : peut-être un défaut de l'installation plutôt que du fichier.
            niveau = logging.ERROR if code > 0 and code != CODE_MEMOIRE else logging.WARNING
            fin = journal.decode("utf-8", errors="replace").strip()
            logger.log(niveau, "Lecture isolée %s %s après %.1f s (plafond %s Mo).%s", cible, raison, duree, memoire_mo, f"\n{fin}" if fin else "")
            raise LimiteDepassee(raison)
        with open(resultat, "rb") as fichier:
            reponse = _Depickleur(fichier).load()
    genre = reponse[0]
    if genre == "resultat":
        return reponse[1]
    if genre == "metier" and tuple(reponse[1:3]) in EXCEPTIONS_TRANSMISES:
        _, module, nom, message = reponse
        raise getattr(importlib.import_module(module), nom)(message)
    _, nom, message, trace = reponse
    logger.error("Lecture isolée %s : exception %s dans le processus de lecture.\n%s", cible, nom, trace)
    raise ErreurEnfant(nom, message)


def _attendre(enfant: subprocess.Popen, delai: float, journal: bytearray) -> bool:
    """L'enfant s'est-il terminé dans le délai ? Il n'est pas encore récolté (WNOWAIT) : son numéro de groupe
    reste réservé, _arreter peut tuer ce qu'il a laissé derrière lui sans risquer de viser un autre groupe."""
    limite = time.monotonic() + delai
    pause = 0.005
    ouvert = True
    while True:
        try:
            if os.waitid(os.P_PID, enfant.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                return True
        except ChildProcessError:
            # Récolté sans nous (SIGCHLD ignoré par le processus) : on suit sa présence dans /proc.
            if not Path(f"/proc/{enfant.pid}").exists():
                return True
        if time.monotonic() >= limite:
            return False
        if ouvert:
            ouvert = _lire_journal(enfant, journal, pause)
        else:
            time.sleep(pause)
        pause = min(pause * 2, 0.1)


def _lire_journal(enfant: subprocess.Popen, journal: bytearray, attente: float) -> bool:
    """Lit ce que l'enfant a écrit (au plus attente secondes d'attente) ; False quand le tube est fermé."""
    if not select.select([enfant.stdout], [], [], attente)[0]:
        return True
    morceau = os.read(enfant.stdout.fileno(), 65536)
    journal += morceau
    del journal[:-JOURNAL_GARDE]
    return bool(morceau)


def _arreter(enfant: subprocess.Popen, journal: bytearray) -> None:
    """Tue tout le groupe de l'enfant (lui-même s'il tourne encore, LibreOffice, Tesseract…), le récolte,
    puis lit la fin de sa sortie d'erreur."""
    try:
        os.killpg(enfant.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    enfant.wait()
    try:
        for _ in range(100):  # le tube contient au plus 64 Ko : quelques lectures suffisent
            if not _lire_journal(enfant, journal, 0):
                break
    finally:
        enfant.stdout.close()


def _nom_signal(numero: int) -> str:
    try:
        return signal.Signals(numero).name
    except ValueError:
        return str(numero)


class _Depickleur(pickle.Unpickler):
    def find_class(self, module, nom):
        if (module, nom) not in TYPES_RESULTAT:
            raise pickle.UnpicklingError(f"Type inattendu dans le résultat de la lecture isolée : {module}.{nom}")
        return super().find_class(module, nom)


# --- Enfant ---------------------------------------------------------------------------------------------


def _reponse_exception(erreur: BaseException, memoire: int) -> tuple | None:
    """Exception à transmettre au parent ; None si c'est le plafond de mémoire qui a été atteint."""
    if _causee_par_la_memoire(erreur):
        return None
    for classe in type(erreur).__mro__:
        if (classe.__module__, classe.__qualname__) in EXCEPTIONS_TRANSMISES:
            return ("metier", classe.__module__, classe.__qualname__, str(erreur))
    if _pres_du_plafond(memoire):
        return None
    import traceback

    trace = "".join(traceback.format_exception(erreur))[-5000:]
    return ("erreur", type(erreur).__name__, str(erreur)[:1000], trace)


def _causee_par_la_memoire(erreur: BaseException) -> bool:
    vues = set()
    while erreur is not None and id(erreur) not in vues:
        if isinstance(erreur, MemoryError):
            return True
        vues.add(id(erreur))
        erreur = erreur.__cause__ or erreur.__context__
    return False


def _pres_du_plafond(memoire: int) -> bool:
    """La mémoire virtuelle de l'enfant a-t-elle atteint la moitié du plafond ?

    Une bibliothèque C à court de mémoire signale souvent une erreur quelconque plutôt qu'une MemoryError
    (libxml2, par lxml : « XMLSyntaxError: unknown error » pour 90 Mo de liens d'une feuille). Un fichier
    simplement abîmé échoue bien plus bas (environ 330 Mo, bibliothèques de lecture chargées).
    """
    if memoire <= 0:
        return False
    try:
        with open("/proc/self/status") as statut:
            pic = next(int(ligne.split()[1]) * 1024 for ligne in statut if ligne.startswith("VmPeak:"))
    except (OSError, StopIteration, ValueError):
        return False
    return pic >= memoire // 2


def _plafonner(ressource: int, souple: int, dur: int) -> None:
    """Pose un plafond, sans dépasser le plafond dur déjà imposé à ce processus (qui ne peut que baisser)."""
    _, actuel = resource.getrlimit(ressource)
    if actuel != resource.RLIM_INFINITY:
        souple, dur = min(souple, actuel), min(dur, actuel)
    resource.setrlimit(ressource, (souple, dur))


def _enfant(memoire: int, cpu: int, requete: Path, resultat: Path) -> None:
    # Plafonds posés avant tout import lourd ; hérités par LibreOffice et Tesseract (chacun pour son compte).
    if memoire > 0:
        _plafonner(resource.RLIMIT_AS, memoire, memoire)
    if cpu > 0:
        _plafonner(resource.RLIMIT_CPU, cpu, cpu + 5)  # SIGXCPU, puis SIGKILL 5 s plus tard
    _plafonner(resource.RLIMIT_CORE, 0, 0)  # pas de fichier « core » après un plantage
    _plafonner(resource.RLIMIT_FSIZE, FICHIER_ECRIT_MAX, FICHIER_ECRIT_MAX)  # conversion, image d'une page, résultat
    reponse = None
    try:
        import django

        django.setup()
        with open(requete, "rb") as fichier:
            cible, args, kwargs = pickle.load(fichier)  # écrit par le parent
        module, _, nom = cible.partition(":")
        reponse = ("resultat", getattr(importlib.import_module(module), nom)(*args, **kwargs))
    except MemoryError:
        pass  # la mémoire manque : rien n'est écrit (et la pile, qui retient la mémoire prise, est libérée ici)
    except BaseException as erreur:  # noqa: BLE001 - tout est transmis au parent
        try:
            reponse = _reponse_exception(erreur, memoire)
        except MemoryError:
            reponse = None
    if reponse is None:
        os._exit(CODE_MEMOIRE)
    temporaire = resultat.with_suffix(".tmp")
    try:
        with open(temporaire, "wb") as fichier:
            pickle.dump(reponse, fichier, protocol=pickle.HIGHEST_PROTOCOL)
    except MemoryError:
        os._exit(CODE_MEMOIRE)
    os.replace(temporaire, resultat)  # résultat complet ou absent


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    _enfant(int(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    sys.stdout.flush()
    os._exit(0)  # sans attendre le ramasse-miettes d'un gros résultat
