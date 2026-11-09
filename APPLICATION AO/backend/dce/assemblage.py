"""Assemblage du DCE : arborescence classée, bordereau des pièces, dossier .zip.

    DCE <opération> - Indice A/
      00 - Bordereau des pièces.pdf
      00 - Lettre de consultation.pdf          (dossier envoyé à une entreprise)
      01 - Pièces administratives/
        RC - Règlement de la consultation.pdf
        CCAP - Cahier des clauses administratives particulières.pdf
        Actes d'engagement/AE Lot 08 - Menuiseries extérieures.docx (+ .pdf)
      02 - Pièces techniques/
        Lot 08 - Menuiseries extérieures/
          CCTP Lot 08 - Menuiseries extérieures.pdf
          DPGF Lot 08 - Menuiseries extérieures (à compléter).xlsx (+ .pdf)
          Plans du lot/…   Documents du lot/…
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
LONGUEUR_NOM = 70  # Windows limite les chemins à 260 caractères une fois le dossier décompressé


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
    return nom_sur(f"Lot {lot.code} - {lot.intitule}", 55)


def racine(projet: Projet, indice: str) -> str:
    return nom_sur(f"DCE {projet.nom} - Indice {indice}", 60)


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
        fichiers.append(Fichier(f"{dossier}/{nom_sur(base)}.pdf", designation, "PDF", lambda p=piece: exporter_pdf(document_piece(p))))
        if avec_word or word_toujours:
            fichiers.append(Fichier(f"{dossier}/{nom_sur(base)}.docx", designation, "Word", lambda p=piece: exporter_docx(document_piece(p))))

    if (rc := pieces.get((TypePiece.RC, None))) is not None:
        piece_ecrite(DOSSIER_ADMINISTRATIF, "RC - Règlement de la consultation", "Règlement de la consultation (RC)", rc)
    if (ccap := pieces.get((TypePiece.CCAP, None))) is not None:
        piece_ecrite(DOSSIER_ADMINISTRATIF, "CCAP - Cahier des clauses administratives particulières", "Cahier des clauses administratives particulières (CCAP)", ccap)
    for lot in lots:
        if (ae := pieces.get((TypePiece.AE, lot.pk))) is not None:
            # L'entreprise complète et signe l'acte d'engagement : version Word toujours fournie.
            piece_ecrite(f"{DOSSIER_ADMINISTRATIF}/Actes d'engagement", f"AE {nom_lot(lot)}", f"Acte d'engagement – lot {lot.code} {lot.intitule}", ae, word_toujours=True)

    jointes = list(PieceJointe.objects.filter(projet=projet).select_related("lot"))
    for lot in lots:
        dossier_lot = f"{DOSSIER_TECHNIQUE}/{nom_lot(lot)}"
        structure = None
        if _a_un_cctp(lot):
            structure = structurer(lot)
            base = f"CCTP {nom_lot(lot)}"
            designation = f"CCTP – lot {lot.code} {lot.intitule}"
            fichiers.append(Fichier(f"{dossier_lot}/{nom_sur(base)}.pdf", designation, "PDF", lambda s=structure: exporter_cctp_pdf(s)))
            if avec_word:
                fichiers.append(Fichier(f"{dossier_lot}/{nom_sur(base)}.docx", designation, "Word", lambda s=structure: exporter_cctp_docx(s)))
        if _a_une_dpgf(lot):
            structure = structure or structurer(lot)
            base = nom_sur(f"DPGF {nom_lot(lot)} (à compléter)")
            designation = f"DPGF – lot {lot.code} {lot.intitule} (à compléter par l'entreprise)"
            fichiers.append(Fichier(f"{dossier_lot}/{base}.xlsx", designation, "Excel", lambda s=structure: exporter_dpgf_xlsx(s)))
            fichiers.append(Fichier(f"{dossier_lot}/{base}.pdf", designation, "PDF", lambda s=structure: exporter_dpgf_pdf(s)))
        for jointe in (j for j in jointes if j.lot_id == lot.pk):
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
    dossier_racine = racine(projet, indice)
    tete = [Fichier("00 - Bordereau des pièces.pdf", "Bordereau des pièces du dossier", "PDF")]
    if entreprise is not None and lettre:
        tete.append(Fichier("00 - Lettre de consultation.pdf", "Lettre de consultation", "PDF"))
    tete[0].produire = lambda: bordereau_pdf(projet, indice, tete + fichiers, entreprise, lots)
    if len(tete) > 1:
        tete[1].produire = lambda: lettre_pdf(projet, indice, entreprise, lots or [], lettre)

    contenu = []
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for fichier in tete + fichiers:
            chemin = f"{dossier_racine}/{fichier.chemin}"
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
