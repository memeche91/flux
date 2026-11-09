"""Assemblage du DCE : arborescence classée, bordereau des pièces, dossier .zip.

    DCE <opération> - Indice A.zip
      00 - Bordereau des pièces.pdf
      00 - Lettre de consultation.pdf          (dossier envoyé à une entreprise)
      01 - Pièces administratives/
        RC - Règlement de la consultation.pdf
        CCAP - Cahier des clauses administratives particulières.pdf
        Actes d'engagement/AE lot 08 - Menuiseries extérieures.docx (+ .pdf)
      02 - Pièces techniques/
        Lot 08 - Menuiseries extérieures/
          CCTP lot 08.pdf
          DPGF lot 08 (à compléter).xlsx (+ .pdf)
          Plans du lot/…   Documents du lot/…

Pas de dossier racine dans le .zip : « Extraire tout » de Windows en crée déjà un au nom
du fichier. Les noms sont bornés pour rester sous la limite de 260 caractères de Windows
une fois le dossier extrait (Téléchargements + nom du .zip + chemin interne).
      03 - Plans/   04 - Études et rapports/   05 - Diagnostics/
      06 - Sécurité et santé (PGC)/   07 - Autres documents/
"""
from __future__ import annotations

import re
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from django.template.loader import render_to_string
from django.utils import timezone

from projets.exports.cctp_docx import exporter_cctp_docx, exporter_docx
from projets.exports.document import POLICES_PDF
from projets.exports.dpgf_xlsx import exporter_dpgf_xlsx
from projets.exports.pdf import exporter_cctp_pdf, exporter_dpgf_pdf, exporter_pdf
from projets.models import GenrePoste, LotProjet, PieceEcrite, Projet, TypePiece
from projets.pieces import document_piece
from projets.structure import structurer

from .models import CategoriePieceJointe, PieceJointe

DOSSIER_ADMINISTRATIF = "01 - Pièces administratives"
DOSSIER_TECHNIQUE = "02 - Pièces techniques"
DOSSIERS_CATEGORIES = {
    CategoriePieceJointe.PLANS: "03 - Plans",
    CategoriePieceJointe.ETUDES: "04 - Études et rapports",
    CategoriePieceJointe.DIAGNOSTICS: "05 - Diagnostics",
    CategoriePieceJointe.SPS: "06 - Sécurité et santé (PGC)",
    CategoriePieceJointe.AUTRES: "07 - Autres documents",
}
LONGUEUR_NOM = 50  # nom de fichier ; dossier de lot 40 ; racine 45 : chemin interne de 135 caractères au plus


@dataclass
class Fichier:
    chemin: str
    designation: str
    format: str
    produire: Callable[[], bytes] | None = None
    source: Path | None = None


def nom_sur(texte: str, longueur: int = LONGUEUR_NOM) -> str:
    """Nom de fichier ou de dossier accepté par Windows."""
    texte = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", texte)
    texte = " ".join(texte.split()).strip(" .")
    if len(texte) > longueur:
        texte = texte[:longueur].rsplit(" ", 1)[0].strip(" .-–") or texte[:longueur]
    return texte or "Sans titre"


def nom_lot(lot: LotProjet) -> str:
    return nom_sur(f"Lot {lot.code} - {lot.intitule}", 40)


def racine(projet: Projet, indice: str) -> str:
    """« DCE <opération> - Indice B » : l'indice est toujours conservé, le nom de l'opération raccourci."""
    suffixe = f" - Indice {indice}"
    return f"DCE {nom_sur(projet.nom, max(10, 45 - 4 - len(suffixe)))}{suffixe}"


def nom_zip(projet: Projet, indice: str, entreprise=None) -> str:
    base = racine(projet, indice)
    if entreprise is not None:
        base = f"{base} - {nom_sur(entreprise.raison_sociale, 24)}"
    return f"{base}.zip"


class DocumentManquant(Exception):
    pass


def _pieces(projet: Projet) -> dict[tuple[str, int | None], PieceEcrite]:
    return {(p.type_piece, p.lot_id): p for p in projet.pieces.select_related("lot", "projet")}


def _a_un_cctp(lot: LotProjet) -> bool:
    return lot.postes.exists()


def _a_une_dpgf(lot: LotProjet) -> bool:
    return lot.postes.filter(genre=GenrePoste.OUVRAGE).exists()


def plan(projet: Projet, *, lots: list[LotProjet] | None = None, avec_word: bool = False) -> list[Fichier]:
    """Liste ordonnée des fichiers du DCE (sans le bordereau ni la lettre), produits à la demande."""
    tous_les_lots = list(projet.lots.order_by("ordre", "code"))
    lots = tous_les_lots if lots is None else [l for l in tous_les_lots if l in lots]
    pieces = _pieces(projet)
    fichiers: list[Fichier] = []

    def piece_ecrite(dossier: str, base: str, designation: str, piece: PieceEcrite, word_toujours: bool = False):
        nom = nom_sur(base, 60)  # dossier administratif court : le titre complet tient
        fichiers.append(Fichier(f"{dossier}/{nom}.pdf", designation, "PDF", lambda p=piece: exporter_pdf(document_piece(p))))
        if avec_word or word_toujours:
            fichiers.append(Fichier(f"{dossier}/{nom}.docx", designation, "Word", lambda p=piece: exporter_docx(document_piece(p))))

    if (rc := pieces.get((TypePiece.RC, None))) is not None:
        piece_ecrite(DOSSIER_ADMINISTRATIF, "RC - Règlement de la consultation", "Règlement de la consultation (RC)", rc)
    if (ccap := pieces.get((TypePiece.CCAP, None))) is not None:
        piece_ecrite(DOSSIER_ADMINISTRATIF, "CCAP - Cahier des clauses administratives particulières", "Cahier des clauses administratives particulières (CCAP)", ccap)
    for lot in lots:
        if (ae := pieces.get((TypePiece.AE, lot.pk))) is not None:
            # L'entreprise complète et signe l'acte d'engagement : version Word toujours fournie.
            base = nom_sur(f"AE lot {lot.code} - {lot.intitule}", 45)
            piece_ecrite(f"{DOSSIER_ADMINISTRATIF}/Actes d'engagement", base, f"Acte d'engagement – lot {lot.code} {lot.intitule}", ae, word_toujours=True)

    jointes = list(PieceJointe.objects.filter(projet=projet).select_related("lot"))
    for lot in lots:
        dossier_lot = f"{DOSSIER_TECHNIQUE}/{nom_lot(lot)}"
        structure = None
        if _a_un_cctp(lot):
            structure = structurer(lot)
            base = nom_sur(f"CCTP lot {lot.code}")
            designation = f"CCTP – lot {lot.code} {lot.intitule}"
            fichiers.append(Fichier(f"{dossier_lot}/{base}.pdf", designation, "PDF", lambda s=structure: exporter_cctp_pdf(s)))
            if avec_word:
                fichiers.append(Fichier(f"{dossier_lot}/{base}.docx", designation, "Word", lambda s=structure: exporter_cctp_docx(s)))
        if _a_une_dpgf(lot):
            structure = structure or structurer(lot)
            base = nom_sur(f"DPGF lot {lot.code} (à compléter)")
            designation = f"DPGF – lot {lot.code} {lot.intitule} (à compléter par l'entreprise)"
            fichiers.append(Fichier(f"{dossier_lot}/{base}.xlsx", designation, "Excel", lambda s=structure: exporter_dpgf_xlsx(s)))
            fichiers.append(Fichier(f"{dossier_lot}/{base}.pdf", designation, "PDF", lambda s=structure: exporter_dpgf_pdf(s)))
        # Plans du lot d'abord, puis les autres documents : chaque dossier reste groupé.
        du_lot = [j for j in jointes if j.lot_id == lot.pk]
        for jointe in [j for j in du_lot if j.categorie == CategoriePieceJointe.PLANS] + [j for j in du_lot if j.categorie != CategoriePieceJointe.PLANS]:
            sous_dossier = "Plans du lot" if jointe.categorie == CategoriePieceJointe.PLANS else "Documents du lot"
            fichiers.append(_fichier_joint(f"{dossier_lot}/{sous_dossier}", jointe))

    for categorie, dossier in DOSSIERS_CATEGORIES.items():
        for jointe in (j for j in jointes if j.lot_id is None and j.categorie == categorie):
            fichiers.append(_fichier_joint(dossier, jointe))
    return _sans_doublons(fichiers)


def _fichier_joint(dossier: str, jointe: PieceJointe) -> Fichier:
    extension = Path(jointe.nom_original).suffix.lower()
    base = nom_sur(jointe.titre, LONGUEUR_NOM - len(extension))
    return Fichier(f"{dossier}/{base}{extension}", jointe.titre, extension.lstrip(".").upper() or "Fichier", source=Path(jointe.fichier.path))


def _sans_doublons(fichiers: list[Fichier]) -> list[Fichier]:
    vus: set[str] = set()
    for fichier in fichiers:
        chemin = fichier.chemin
        numero = 2
        while chemin.lower() in vus:
            base, point, extension = fichier.chemin.rpartition(".")
            chemin = f"{base} ({numero}).{extension}" if point else f"{fichier.chemin} ({numero})"
            numero += 1
        fichier.chemin = chemin
        vus.add(chemin.lower())
    return fichiers


def _rendre_pdf(gabarit: str, contexte: dict) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_to_string(gabarit, contexte)).write_pdf()


def _contexte(projet: Projet, indice: str) -> dict:
    return {
        "projet": projet,
        "indice": indice,
        "date": timezone.localdate(),
        "police": POLICES_PDF.get(projet.police, POLICES_PDF["Arial"]),
        "couleur_titres": projet.couleur_titres,
        "couleur_tableaux": projet.couleur_tableaux,
    }


def bordereau_pdf(projet: Projet, indice: str, fichiers: list[Fichier], entreprise=None, lots=None) -> bytes:
    rubriques: list[dict] = []
    for numero, fichier in enumerate(fichiers, start=1):
        dossier = fichier.chemin.rsplit("/", 1)[0] if "/" in fichier.chemin else ""
        if not rubriques or rubriques[-1]["dossier"] != dossier:
            rubriques.append({"dossier": dossier, "fichiers": []})
        rubriques[-1]["fichiers"].append({"numero": numero, "nom": fichier.chemin.rsplit("/", 1)[-1], "designation": fichier.designation, "format": fichier.format})
    return _rendre_pdf("dce/bordereau.html", {**_contexte(projet, indice), "rubriques": rubriques, "entreprise": entreprise, "lots": lots or []})


def lettre_pdf(projet: Projet, indice: str, entreprise, lots: list[LotProjet], texte: str) -> bytes:
    paragraphes = [p.strip() for p in re.split(r"\n\s*\n", texte) if p.strip()]
    return _rendre_pdf("dce/lettre.html", {**_contexte(projet, indice), "entreprise": entreprise, "lots": lots, "paragraphes": paragraphes})


def ecrire_zip(destination: Path, projet: Projet, indice: str, fichiers: list[Fichier], *, entreprise=None, lots=None, lettre: str = "") -> list[dict]:
    """Écrit le .zip et renvoie son contenu (chemin, taille) pour l'affichage et le bordereau."""
    for fichier in fichiers:
        if fichier.source is not None and not fichier.source.exists():
            raise DocumentManquant(
                f"Document joint « {fichier.designation} » introuvable sur le disque : retirez-le puis déposez-le de nouveau."
            )
    tete = [Fichier("00 - Bordereau des pièces.pdf", "Bordereau des pièces du dossier", "PDF")]
    if entreprise is not None and lettre:
        tete.append(Fichier("00 - Lettre de consultation.pdf", "Lettre de consultation", "PDF"))
    tete[0].produire = lambda: bordereau_pdf(projet, indice, tete + fichiers, entreprise, lots)
    if len(tete) > 1:
        tete[1].produire = lambda: lettre_pdf(projet, indice, entreprise, lots or [], lettre)

    contenu = []
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for fichier in tete + fichiers:
            chemin = fichier.chemin
            if fichier.source is not None:
                archive.write(fichier.source, chemin)
                taille = fichier.source.stat().st_size
            else:
                octets = fichier.produire()
                archive.writestr(chemin, octets)
                taille = len(octets)
            contenu.append({"chemin": chemin, "taille": taille, "designation": fichier.designation})
    return contenu


def produire_dossier(projet: Projet, indice: str, *, lots=None, avec_word=False, entreprise=None, lettre="") -> tuple[Path, list[dict]]:
    fichiers = plan(projet, lots=lots, avec_word=avec_word)
    temporaire = Path(tempfile.mkstemp(suffix=".zip", prefix="dce-")[1])
    try:
        contenu = ecrire_zip(temporaire, projet, indice, fichiers, entreprise=entreprise, lots=lots, lettre=lettre)
    except Exception:
        temporaire.unlink(missing_ok=True)
        raise
    return temporaire, contenu
