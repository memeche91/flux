"""Import d'un carnet d'adresses existant (Excel ou CSV) : colonnes reconnues automatiquement."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from articles.normalisation import normaliser
from referentiel.models import Lot

from .models import Contact, Entreprise

COLONNES = {
    "raison_sociale": ["raison sociale", "entreprise", "societe", "nom entreprise", "nom de l entreprise", "denomination", "nom"],
    "siret": ["siret", "n siret", "numero siret", "siren"],
    "adresse": ["adresse", "rue", "adresse postale"],
    "code_postal": ["code postal", "cp"],
    "ville": ["ville", "commune", "localite"],
    "telephone": ["telephone", "tel", "standard", "portable", "mobile"],
    "email": ["email", "e mail", "mail", "courriel", "adresse mail", "adresse e mail", "adresse de messagerie", "messagerie", "adresse electronique"],
    "site_web": ["site", "site web", "site internet", "internet"],
    "contact": ["contact", "interlocuteur", "nom du contact", "nom contact", "responsable"],
    "lots": ["lot", "lots", "corps d etat", "corps d etats", "specialite", "specialites", "metier", "metiers", "activite", "activites"],
    "qualifications": ["qualification", "qualifications", "qualibat", "certification", "certifications", "labels"],
    "notes": ["notes", "note", "commentaire", "commentaires", "remarques", "observations"],
}


@dataclass
class Bilan:
    creees: int = 0
    mises_a_jour: int = 0
    ignorees: list[str] = field(default_factory=list)
    colonnes: dict[str, str] = field(default_factory=dict)


class ImportImpossible(Exception):
    pass


LIGNES_MAX = 100_000
LIGNES_VIDES_MAX = 1_000  # feuilles « formatées » sur un million de lignes : on s'arrête après ce blanc
TROP_LONG = "Fichier trop long : un annuaire importé compte au plus 100 000 lignes."


def _lignes(nom: str, contenu: bytes) -> list[list[str]]:
    if nom.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        from bibliotheque.lecture import decompression_excessive

        try:
            if decompression_excessive(io.BytesIO(contenu), ".xlsx"):
                raise ImportImpossible("Fichier anormalement volumineux une fois décompressé : il n’a pas été importé.")
            classeur = load_workbook(io.BytesIO(contenu), read_only=True, data_only=True)
            feuille = classeur.worksheets[0]
            lignes: list[list[str]] = []
            vides = 0
            for ligne in feuille.iter_rows(values_only=True):
                cellules = [_cellule(v) for v in ligne]
                vides = 0 if any(cellules) else vides + 1
                if vides > LIGNES_VIDES_MAX:
                    break
                if len(lignes) >= LIGNES_MAX:
                    raise ImportImpossible(TROP_LONG)
                lignes.append(cellules)
            return lignes
        except ImportImpossible:
            raise
        except Exception:  # noqa: BLE001 - classeur protégé, ancien .xls renommé, fichier abîmé
            raise ImportImpossible(
                "Classeur illisible ou protégé par un mot de passe : enregistrez-le en .xlsx sans mot de passe, ou en CSV."
            ) from None
    if nom.lower().endswith((".csv", ".txt")):
        for encodage in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                texte = contenu.decode(encodage)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialecte = csv.Sniffer().sniff(texte[:5000], delimiters=";,\t")
        except csv.Error:
            dialecte = csv.excel
            dialecte.delimiter = ";"
        return [[c.strip() for c in ligne] for ligne in csv.reader(io.StringIO(texte), dialecte)]
    raise ImportImpossible("Format non reconnu : importez un fichier Excel (.xlsx) ou CSV.")


def _cellule(valeur) -> str:
    if valeur is None:
        return ""
    if isinstance(valeur, float) and valeur.is_integer():
        valeur = int(valeur)
    return str(valeur).strip()


MOTS_EMAIL = ("mail", "messagerie", "courriel", "electronique")
ORDRE = ["email", "raison_sociale", "siret", "code_postal", "ville", "telephone", "site_web", "contact", "lots", "qualifications", "notes", "adresse"]


def _reperer_colonnes(lignes: list[list[str]]) -> tuple[int, dict[str, int]]:
    """Ligne d'en-tête (parmi les 10 premières) et position de chaque colonne reconnue.

    Les correspondances exactes passent avant les débuts de mots (« Adresse mail » est un e-mail,
    pas une adresse postale) ; « Nom » ne désigne l'entreprise que s'il n'y a pas de colonne Société.
    """
    for indice, ligne in enumerate(lignes[:10]):
        noms = [normaliser(cellule) for cellule in ligne]
        trouvees: dict[str, int] = {}
        for exact in (True, False):
            for champ in ORDRE:
                if champ in trouvees:
                    continue
                synonymes = COLONNES[champ]
                for position, nom in enumerate(noms):
                    if not nom or position in trouvees.values():
                        continue
                    if champ == "adresse" and any(m in nom for m in MOTS_EMAIL):
                        continue
                    if champ == "raison_sociale" and nom == "nom" and any(n in ("societe", "entreprise", "raison sociale", "denomination") for n in noms):
                        continue
                    prefixes = [x for x in synonymes if x != "nom" and (len(x) > 3 or x in ("rue", "tel", "cp"))]
                    if (nom in synonymes) if exact else any(nom.startswith(x + " ") for x in prefixes):
                        trouvees[champ] = position
                        break
        if "raison_sociale" in trouvees and len(trouvees) >= 2:
            if trouvees.get("contact") is None and noms[trouvees["raison_sociale"]] != "nom" and "nom" in noms:
                trouvees["contact"] = noms.index("nom")
            return indice, trouvees
    raise ImportImpossible(
        "Colonnes introuvables : la première ligne doit contenir au moins « Entreprise » (ou « Raison sociale ») "
        "et une autre colonne (ville, e-mail, téléphone, lots…)."
    )


def _lots_depuis(texte: str, lots: list[Lot]) -> tuple[list[Lot], list[str]]:
    trouves, inconnus = [], []
    for morceau in re.split(r"[;,/+\n]| et ", texte or ""):
        cle = normaliser(morceau)
        if not cle:
            continue
        code = re.match(r"(?:lot )?0*(\d{1,2})\b", cle)  # « 08 », « Lot 8 », « 08 - Menuiseries »
        lot = None
        if code:
            lot = next((l for l in lots if l.code.lstrip("0") == code.group(1).lstrip("0")), None)
        if lot is None and len(cle) >= 4:
            lot = next((l for l in lots if normaliser(l.intitule) in cle or cle in normaliser(l.intitule)), None)
        if lot is None:
            inconnus.append(morceau.strip())
        elif lot not in trouves:
            trouves.append(lot)
    return trouves, inconnus


def _siret(valeur: str) -> str:
    chiffres = re.sub(r"\D", "", valeur or "")
    if len(chiffres) in (8, 13):  # zéro initial perdu par Excel
        chiffres = "0" + chiffres
    return chiffres if len(chiffres) in (9, 14) else ""


def cp_normalise(valeur: str) -> str:
    """« 6000 » (Excel a perdu le zéro) → « 06000 »."""
    valeur = (valeur or "").strip()
    return valeur.zfill(5) if valeur.isdigit() and len(valeur) == 4 else valeur


def _telephone(valeur: str) -> str:
    valeur = (valeur or "").strip()
    return "0" + valeur if valeur.isdigit() and len(valeur) == 9 else valeur


def _email(valeur: str) -> str:
    valeur = (valeur or "").strip()
    try:
        validate_email(valeur)
        return valeur
    except ValidationError:
        return ""


def doublon(raison_sociale: str, siret: str, code_postal: str, ville: str, exclure: int | None = None) -> Entreprise | None:
    entreprises = Entreprise.objects.exclude(pk=exclure) if exclure else Entreprise.objects.all()
    if siret:
        trouvee = entreprises.filter(siret=siret).first()
        if trouvee:
            return trouvee
    nom = normaliser(raison_sociale)
    if not nom:
        return None
    cp = cp_normalise(code_postal)
    for candidate in entreprises.filter(texte_recherche__startswith=nom):
        if normaliser(candidate.raison_sociale) != nom:
            continue
        # Même nom : c'est la même entreprise, sauf si le code postal ou la ville diffèrent.
        cp_differents = cp and candidate.code_postal and cp != cp_normalise(candidate.code_postal)
        villes_differentes = ville and candidate.ville and normaliser(ville) != normaliser(candidate.ville)
        if not cp_differents and not villes_differentes:
            return candidate
    return None


@transaction.atomic
def importer(nom: str, contenu: bytes) -> Bilan:
    lignes = _lignes(nom, contenu)
    entete, colonnes = _reperer_colonnes(lignes)
    bilan = Bilan(colonnes={champ: lignes[entete][position] for champ, position in colonnes.items()})
    lots = list(Lot.objects.all())

    for numero, ligne in enumerate(lignes[entete + 1 :], start=entete + 2):
        valeur = lambda champ: (ligne[colonnes[champ]].strip() if champ in colonnes and colonnes[champ] < len(ligne) else "")  # noqa: E731
        raison_sociale = valeur("raison_sociale")
        if not raison_sociale:
            if any(c.strip() for c in ligne):
                bilan.ignorees.append(f"Ligne {numero} : nom de l'entreprise absent.")
            continue
        lots_trouves, inconnus = _lots_depuis(valeur("lots"), lots)
        donnees = {
            "raison_sociale": raison_sociale[:255],
            "siret": _siret(valeur("siret")),
            "adresse": valeur("adresse")[:255],
            "code_postal": cp_normalise(valeur("code_postal"))[:10],
            "ville": valeur("ville")[:120],
            "telephone": _telephone(valeur("telephone"))[:30],
            "email": _email(valeur("email")),
            "site_web": valeur("site_web")[:255],
            "qualifications": valeur("qualifications")[:500],
            "specialites": ", ".join(inconnus)[:500],
            "notes": valeur("notes"),
        }
        entreprise = doublon(donnees["raison_sociale"], donnees["siret"], donnees["code_postal"], donnees["ville"])
        if entreprise is None:
            entreprise = Entreprise.objects.create(**donnees)
            bilan.creees += 1
        else:
            # Les informations déjà saisies dans l'application ne sont jamais écrasées.
            for champ, contenu_champ in donnees.items():
                if contenu_champ and not getattr(entreprise, champ):
                    setattr(entreprise, champ, contenu_champ)
            entreprise.save()
            bilan.mises_a_jour += 1
        entreprise.lots.add(*lots_trouves)
        nom_contact = valeur("contact")
        if nom_contact and not entreprise.contacts.filter(nom__iexact=nom_contact).exists():
            Contact.objects.create(
                entreprise=entreprise, nom=nom_contact[:150], email=donnees["email"], telephone=donnees["telephone"],
                principal=not entreprise.contacts.exists(),
            )
    return bilan
