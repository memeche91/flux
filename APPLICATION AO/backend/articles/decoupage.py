"""Découpage d'un document (CCTP, CCAP, RC, AE) en articles.

Un article commence à chaque titre et contient le texte jusqu'au titre suivant.
Les titres viennent des styles Word (Titre 1, 2, 3…) ou sont reconnus dans le
texte (« 3.2.4 Châssis aluminium », « ARTICLE 4 – PÉNALITÉS », « LOT 08 – … »).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .normalisation import detecter_lot, est_ligne_sommaire, est_majuscules, extraire_references, normaliser

TAILLE_MIN_CONTENU = 15
TAILLE_MAX_CONTENU = 100_000

_ARTICLE = re.compile(r"^art(?:icle)?\.?\s*(\d{1,3}(?:\.\d{1,3}){0,5})\s*(?:[-–:.)]\s*)?(.*)$", re.IGNORECASE)
_CHAPITRE = re.compile(r"^(chapitre|titre|partie|section)\s+(\d{1,2}|[IVXLC]{1,6})\b\s*(?:[-–:.]\s*)?(.*)$", re.IGNORECASE)
_LOT = re.compile(r"^lot\s*(?:n\s*[°o]\.?\s*)?(\d{1,2})\b\s*(?:[-–:.]\s*)?(.*)$", re.IGNORECASE)
_NUMERO_TITRE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){0,5})\.?\s*(?:[-–:)]\s*)?\s(\S.*)$")
_UNITES_DEBUT = {"mm", "cm", "m", "m2", "m3", "ml", "kg", "t", "h", "u", "x", "l", "kn", "mpa", "db", "w", "kw"}

_MOTS_GENERALITES = (
    "generalite",
    "prescriptions generales",
    "prescriptions communes",
    "dispositions generales",
    "clauses generales",
    "objet du",
    "documents de reference",
    "textes de reference",
    "normes et reglement",
    "reglementation",
    "consistance des travaux",
    "etendue des travaux",
    "description generale",
    "hypotheses",
)


@dataclass
class Titre:
    niveau: int
    numero: str
    texte: str

    @property
    def libelle(self) -> str:
        return " ".join(p for p in (self.numero, self.texte) if p)


@dataclass
class ArticleExtrait:
    ordre: int
    numero: str
    titre: str
    chemin: str
    niveau: int
    contenu: str
    categorie: str
    code_lot: str | None
    references: list[str] = field(default_factory=list)


def detecter_titre(texte: str, gras: bool = False) -> Titre | None:
    """Reconnaît un titre dans une ligne de texte, sinon renvoie None."""
    texte = texte.strip()
    if not texte or len(texte) > 160 or est_ligne_sommaire(texte):
        return None

    correspondance = _LOT.match(texte)
    if correspondance:
        return Titre(0, f"Lot {correspondance.group(1).zfill(2)}", correspondance.group(2).strip() or texte)

    correspondance = _CHAPITRE.match(texte)
    if correspondance and (gras or est_majuscules(texte) or len(texte) <= 80):
        numero = f"{correspondance.group(1).capitalize()} {correspondance.group(2)}"
        return Titre(1, numero, correspondance.group(3).strip())

    correspondance = _ARTICLE.match(texte)
    if correspondance:
        numero, titre = correspondance.group(1), correspondance.group(2).strip()
        if titre and not _ressemble_titre(titre, gras):
            return None
        return Titre(numero.count(".") + 1, f"Article {numero}", titre)

    correspondance = _NUMERO_TITRE.match(texte)
    if correspondance:
        numero, titre = correspondance.group(1), correspondance.group(2).strip()
        composantes = numero.split(".")
        if any(int(c) > 99 for c in composantes) or not _ressemble_titre(titre, gras):
            return None
        if len(composantes) == 1 and (int(numero) > 30 or not (gras or est_majuscules(titre))):
            return None  # simple liste numérotée dans le corps du texte
        return Titre(len(composantes), numero, titre)
    return None


def _ressemble_titre(titre: str, gras: bool) -> bool:
    if len(titre) > 120 or titre.endswith((",", ";")) or not re.search(r"[A-Za-zÀ-ÿ]", titre):
        return False
    premier_mot = normaliser(titre.split()[0]) if titre.split() else ""
    if premier_mot in _UNITES_DEBUT or not titre[0].isalpha() and titre[0] not in "«\"'(":
        return False
    if titre.endswith(".") and len(titre) > 60 and not gras:
        return False  # phrase plutôt que titre
    return True


def decouper(blocs, *, titre_par_defaut: str, administratif: bool) -> list[ArticleExtrait]:
    """Transforme les blocs lus dans le document en articles."""
    articles: list[ArticleExtrait] = []
    pile: list[Titre] = []
    courant: Titre | None = None
    parents: list[Titre] = []
    lignes: list[str] = []
    preambule: list[str] = []
    titre_trouve = False

    def fermer():
        if courant is None:
            return
        contenu = "\n".join(lignes).strip()
        if len(contenu) < TAILLE_MIN_CONTENU:
            return
        articles.append(_creer_article(len(articles) + 1, courant, parents, contenu, administratif))

    for bloc in blocs:
        titre = None
        if bloc.genre == "titre":
            titre = Titre(bloc.niveau, bloc.numero, bloc.texte)
            # « LOT 03 – GROS ŒUVRE », même précédé d'une numérotation automatique (« 1 »).
            correspondance_lot = detecter_lot(titre.texte) or detecter_lot(titre.libelle)
            if correspondance_lot and not titre.numero.startswith("Lot"):
                titre = Titre(titre.niveau, f"Lot {correspondance_lot}", _LOT.sub(r"\2", titre.texte).strip() or titre.texte)
        elif bloc.genre == "texte":
            if est_ligne_sommaire(bloc.texte):
                continue
            titre = detecter_titre(bloc.texte, bloc.gras)

        if titre is not None:
            fermer()
            titre_trouve = True
            while pile and pile[-1].niveau >= titre.niveau:
                pile.pop()
            parents = list(pile)
            pile.append(titre)
            courant, lignes = titre, []
            continue

        contenu_bloc = [" | ".join(l) for l in bloc.lignes] if bloc.genre == "tableau" else [bloc.texte]
        (lignes if courant is not None else preambule).extend(contenu_bloc)
    fermer()

    texte_preambule = "\n".join(preambule).strip()
    if not titre_trouve and len(texte_preambule) >= TAILLE_MIN_CONTENU:
        return [_creer_article(1, Titre(1, "", titre_par_defaut), [], texte_preambule, administratif)]
    if len(texte_preambule) >= 200:
        articles.insert(0, _creer_article(0, Titre(0, "", "Préambule"), [], texte_preambule, administratif))
    return articles


def _creer_article(ordre: int, titre: Titre, parents: list[Titre], contenu: str, administratif: bool) -> ArticleExtrait:
    hierarchie = [*parents, titre]
    code_lot = next((code for t in reversed(hierarchie) if (code := detecter_lot(t.libelle))), None)
    if administratif:
        categorie = "CLAUSE"
    elif any(mot in normaliser(t.libelle) for t in hierarchie for mot in _MOTS_GENERALITES):
        categorie = "GENERALITES"
    else:
        categorie = "OUVRAGE"
    return ArticleExtrait(
        ordre=ordre,
        numero=titre.numero[:50],
        titre=(titre.texte or titre.numero or "Sans titre")[:500],
        chemin=" › ".join(t.libelle for t in parents)[:1000],
        niveau=max(titre.niveau, 0),
        contenu=contenu[:TAILLE_MAX_CONTENU],
        categorie=categorie,
        code_lot=code_lot,
        references=extraire_references(f"{titre.libelle}\n{contenu}"),
    )
