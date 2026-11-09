"""Outils de normalisation partagés : texte, nombres à la française, unités, lots, normes."""
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def sans_accents(texte: str) -> str:
    texte = texte.replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae").replace("Æ", "AE")
    return "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))


def normaliser(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation : sert à la recherche et aux comparaisons."""
    texte = sans_accents(str(texte or "")).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", texte).split())


def texte_cellule(valeur) -> str:
    if valeur is None:
        return ""
    if isinstance(valeur, float) and valeur.is_integer():
        return str(int(valeur))
    return " ".join(str(valeur).split())


# --- Numérotation des titres -------------------------------------------------

_NUMERO = re.compile(r"^((?:\d{1,3}\.){0,6}\d{1,3})(?:\.|\)|\s*[-–:])?\s+(?=\S)")


def separer_numero(texte: str) -> tuple[str, str]:
    """« 3.2.4 Châssis aluminium » → (« 3.2.4 », « Châssis aluminium »)."""
    correspondance = _NUMERO.match(texte)
    if not correspondance:
        return "", texte.strip()
    return correspondance.group(1), texte[correspondance.end():].strip()


def est_ligne_sommaire(texte: str) -> bool:
    """Ligne de table des matières : « 3.2 Châssis ........ 12 »."""
    return bool(re.search(r"(?:\.\s?){4,}|…{2,}|_{4,}|\t\d+\s*$", texte))


def est_majuscules(texte: str) -> bool:
    lettres = [c for c in texte if c.isalpha()]
    return len(lettres) >= 3 and sum(c.isupper() for c in lettres) / len(lettres) > 0.8


_LOT = re.compile(r"^lot\s+(?:n\s*o?\s+|no\s+)?(\d{1,2})\b")


def detecter_lot(texte: str) -> str | None:
    """« LOT N° 8 – MENUISERIES » → « 08 » (code du lot dans la nomenclature)."""
    correspondance = _LOT.match(normaliser(texte))
    return correspondance.group(1).zfill(2) if correspondance else None


# --- Nombres et unités -------------------------------------------------------

_MAXIMUM = Decimal("100000000000")


def lire_nombre(valeur) -> Decimal | None:
    """Lit « 1 250,50 € », « 1.250,50 », 1250.5… ; renvoie None si ce n'est pas un nombre."""
    if valeur is None or isinstance(valeur, bool):
        return None
    if isinstance(valeur, (int, float, Decimal)):
        try:
            nombre = Decimal(str(valeur))
        except InvalidOperation:
            return None
    else:
        texte = str(valeur).strip().lower().replace("\u2212", "-")  # signe moins typographique
        for parasite in (" ", "\xa0", " ", "€", "eur", "ht", "ttc"):
            texte = texte.replace(parasite, "")
        if not texte or not re.fullmatch(r"-?[\d.,]*\d[\d.,]*", texte):
            return None
        if "," in texte and "." in texte:
            if texte.rfind(",") > texte.rfind("."):
                texte = texte.replace(".", "").replace(",", ".")
            else:
                texte = texte.replace(",", "")
        elif "," in texte:
            texte = texte.replace(",", "") if texte.count(",") > 1 else texte.replace(",", ".")
        elif texte.count(".") > 1 or re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", texte):
            texte = texte.replace(".", "")
        try:
            nombre = Decimal(texte)
        except InvalidOperation:
            return None
    if not nombre.is_finite() or abs(nombre) >= _MAXIMUM:
        return None
    return nombre


def arrondir(nombre: Decimal | None, decimales: int) -> Decimal | None:
    if nombre is None:
        return None
    return nombre.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)


_UNITES = {
    "m2": "m²",
    "m3": "m³",
    "ml": "ml",
    "mlin": "ml",
    "metrelineaire": "ml",
    "m": "m",
    "u": "u",
    "un": "u",
    "unite": "u",
    "unites": "u",
    "nb": "u",
    "nbre": "u",
    "pce": "u",
    "piece": "u",
    "pieces": "u",
    "ens": "ens",
    "ensemble": "ens",
    "ft": "ft",
    "fft": "ft",
    "forfait": "ft",
    "f": "ft",
    "kg": "kg",
    "t": "t",
    "tonne": "t",
    "h": "h",
    "heure": "h",
    "j": "j",
    "jour": "j",
    "l": "l",
    "litre": "l",
    "pm": "pm",
}


def normaliser_unite(unite: str) -> str:
    cle = normaliser(unite).replace(" ", "")
    return _UNITES.get(cle, cle)[:20]


# --- Références normatives ---------------------------------------------------

_DTU = re.compile(r"\b(?:NF\s*)?DTU\s*(?:n\s*°\s*)?(\d{1,2}(?:\.\d{1,2}){0,2})", re.IGNORECASE)
_NF = re.compile(
    r"\bNF\s+(EN\s+ISO|EN|ISO|[A-Z])\s?(\d{1,5}(?:\s?[-‑–]\s?\d{1,4}){0,3})", re.IGNORECASE
)
_EUROCODE = re.compile(r"\bEurocodes?\s*(\d)\b", re.IGNORECASE)
_REGLEMENTATION_THERMIQUE = re.compile(r"\b(RE|RT)\s?(20\d{2})\b")


def extraire_references(texte: str) -> list[str]:
    """Normes et DTU cités : « DTU 36.5 », « NF EN 14351-1 », « RE2020 »…"""
    references: set[str] = set()
    for correspondance in _DTU.finditer(texte):
        references.add(f"DTU {correspondance.group(1)}")
    for correspondance in _NF.finditer(texte):
        prefixe = " ".join(correspondance.group(1).upper().split())
        numero = re.sub(r"\s*[-‑–]\s*", "-", correspondance.group(2))
        references.add(f"NF {prefixe} {numero}")
    for correspondance in _EUROCODE.finditer(texte):
        references.add(f"Eurocode {correspondance.group(1)}")
    for correspondance in _REGLEMENTATION_THERMIQUE.finditer(texte):
        references.add(f"{correspondance.group(1)}{correspondance.group(2)}")
    return sorted(references)[:40]
