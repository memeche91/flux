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
    "email": ["email", "e mail", "mail", "courriel", "adresse mail", "adresse e mail"],
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


def _lignes(nom: str, contenu: bytes) -> list[list[str]]:
    if nom.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        classeur = load_workbook(io.BytesIO(contenu), read_only=True, data_only=True)
        feuille = classeur.worksheets[0]
        return [["" if v is None else str(v).strip() for v in ligne] for ligne in feuille.iter_rows(values_only=True)]
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


def _reperer_colonnes(lignes: list[list[str]]) -> tuple[int, dict[str, int]]:
    """Ligne d'en-tête (parmi les 10 premières) et position de chaque colonne reconnue."""
    for indice, ligne in enumerate(lignes[:10]):
        noms = [normaliser(cellule) for cellule in ligne]
        trouvees: dict[str, int] = {}
        for champ, synonymes in COLONNES.items():
            for position, nom in enumerate(noms):
                if nom and position not in trouvees.values() and (nom in synonymes or any(nom.startswith(s + " ") for s in synonymes if len(s) > 3)):
                    trouvees[champ] = position
                    break
        if "raison_sociale" in trouvees and len(trouvees) >= 2:
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
    return chiffres if len(chiffres) in (9, 14) else ""


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
    for candidate in entreprises.filter(texte_recherche__startswith=nom):
        if normaliser(candidate.raison_sociale) != nom:
            continue
        # Même nom : c'est la même entreprise, sauf si le code postal ou la ville diffèrent.
        cp_differents = code_postal and candidate.code_postal and code_postal.strip() != candidate.code_postal.strip()
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
            "code_postal": valeur("code_postal")[:10],
            "ville": valeur("ville")[:120],
            "telephone": valeur("telephone")[:30],
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
