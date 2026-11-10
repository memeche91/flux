"""Lecture isolée : chaque document reçu est lu dans un processus séparé, plafonné en mémoire et en temps.

Les tests de la suite lisent directement (LECTURE_ISOLEE est faux pendant les tests) ; ceux-ci forcent un vrai
processus séparé, avec des plafonds bas : un fichier ordinaire est lu à l'identique, et un piège qu'aucun
garde-fou statique n'arrête (garde-fou retiré dans l'enfant, ou plafond plus bas que ce qu'il réclame) donne
une ErreurLecture claire sans faire tomber le processus des tests.
"""
import datetime
import io
import os
import pickle
import shutil
import signal
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from . import lecture
from .lecture import (
    MESSAGE_LECTURE_INTERROMPUE,
    ErreurLecture,
    FormatNonAnalyse,
    LectureInterrompue,
    lire_document,
    lire_document_direct,
    lire_isole,
)
from .lecture_isolee import ErreurEnfant, LimiteDepassee, executer_isole

# --- Fonctions exécutées dans le processus séparé ------------------------------------------------------


def lire_sans_plafond_de_pixels(chemin, dossier, **options):
    """lire_document_direct sans le garde-fou des pages géantes : page de 200 × 200 pouces rendue à 300 dpi."""
    lecture.PIXELS_OCR_MAX = 10**15
    with mock.patch.object(lecture.shutil, "which", return_value="tesseract"):  # OCR tenté même sans Tesseract
        return lire_document_direct(chemin, dossier, **options)


def lire_avec_ancien_tableau_docx(chemin, dossier, **options):
    """lire_document_direct avec la lecture des tableaux Word d'avant (_Row.cells : gridSpan sans borne)."""

    def ancienne(tableau):
        lignes = []
        for rangee in tableau.rows:
            cellules, precedente = [], None
            for cellule in rangee.cells:
                if cellule._tc is precedente:
                    continue
                precedente = cellule._tc
                cellules.append(" ".join(cellule.text.split()))
            if any(cellules):
                lignes.append(cellules)
        return lignes

    lecture._lignes_tableau_docx = ancienne
    return lire_document_direct(chemin, dossier, **options)


def attendre_un_petit_enfant(fichier_pid: str):
    """Lance un processus qui dort (comme LibreOffice ou Tesseract), note son numéro et l'attend."""
    dormeur = subprocess.Popen(["sleep", "300"])
    Path(fichier_pid).write_text(str(dormeur.pid))
    dormeur.wait()


def calculer_sans_fin():
    while True:
        pass


def mourir_tue():
    os.kill(os.getpid(), signal.SIGKILL)  # comme le noyau quand le conteneur manque de mémoire


def lever_une_exception_inattendue(*_args, **_options):
    raise KeyError("partie absente")


def remplir_puis_echouer(mo: int):
    """Comme libxml2 à court de mémoire : beaucoup de mémoire prise, puis une erreur quelconque."""
    tampon = bytearray(mo * 1024 * 1024)
    raise ValueError(f"unknown error ({len(tampon)} octets)")


def bavarder_puis_mourir(mo: int):
    """Écrit mo Mo d'avertissements sur la sortie d'erreur, puis meurt."""
    import sys

    ligne = "Avertissement : objet PDF incohérent\n" * 1000
    for _ in range(mo * 1024 * 1024 // len(ligne)):
        sys.stderr.write(ligne)
    sys.stderr.write("dernier message\n")
    sys.stderr.flush()
    os.kill(os.getpid(), signal.SIGKILL)


def rendre_un_objet_inattendu():
    return Path("/")


# --- Fichiers d'essai -----------------------------------------------------------------------------------


def _pdf(objets: list[str]) -> bytes:
    """PDF écrit à la main : objets numérotés à partir de 1 (1 : catalogue)."""
    sortie = b"%PDF-1.4\n"
    positions = []
    for numero, objet in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += f"{numero} 0 obj\n{objet}\nendobj\n".encode("latin-1")
    xref = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode()
    sortie += "".join(f"{position:010d} 00000 n \n" for position in positions).encode()
    sortie += f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return sortie


def pdf_texte(lignes: list[str]) -> bytes:
    """PDF d'une page A4 de texte (police standard)."""
    flux = "BT /F1 11 Tf 14 TL 72 770 Td " + " ".join(f"({ligne}) Tj T*" for ligne in lignes) + " ET"
    return _pdf([
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(flux)} >>\nstream\n{flux}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ])


def pdf_pages(pages: list[list[str]]) -> bytes:
    """PDF A4 de plusieurs pages de texte (police standard)."""
    flux = ["BT /F1 11 Tf 14 TL 72 770 Td " + " ".join(f"({ligne}) Tj T*" for ligne in lignes) + " ET" for lignes in pages]
    n = len(pages)
    objets = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * i} 0 R' for i in range(n))}] /Count {n} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, contenu in enumerate(flux):
        objets.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> "
                      f"/Contents {5 + 2 * i} 0 R >>")
        objets.append(f"<< /Length {len(contenu)} >>\nstream\n{contenu}\nendstream")
    return _pdf(objets)


def pdf_page_geante() -> bytes:
    """Page de 200 × 200 pouces (la plus grande permise) portant une image : lue comme une page scannée (656 octets)."""
    return _pdf([
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 14400 14400] /Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>",
        "<< /Length 30 >>\nstream\nq 100 0 0 100 0 0 cm /Im1 Do Q\nendstream",
        "<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 /Length 1 >>"
        "\nstream\n\x80\nendstream",
    ])


def docx_cellule(grid_span: int) -> bytes:
    """Tableau Word d'une cellule « Prix » qui déclare couvrir grid_span colonnes."""
    from docx import Document

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    corps = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {w}><w:body>'
        '<w:p><w:r><w:t>Début</w:t></w:r></w:p><w:tbl><w:tblGrid><w:gridCol/></w:tblGrid><w:tr>'
        f'<w:tc><w:tcPr><w:gridSpan w:val="{grid_span}"/></w:tcPr><w:p><w:r><w:t>Prix</w:t></w:r></w:p></w:tc>'
        "</w:tr></w:tbl><w:p><w:r><w:t>Fin</w:t></w:r></w:p></w:body></w:document>"
    )
    gabarit = io.BytesIO()
    Document().save(gabarit)
    flux = io.BytesIO()
    with zipfile.ZipFile(gabarit) as source, zipfile.ZipFile(flux, "w", zipfile.ZIP_DEFLATED) as cible:
        for info in source.infolist():
            cible.writestr(info.filename, corps.encode() if info.filename == "word/document.xml" else source.read(info))
    return flux.getvalue()


def _docx_ordinaire() -> bytes:
    from docx import Document

    document = Document()
    document.add_heading("Lot 08 – Menuiseries extérieures", level=1)
    document.add_heading("Objet du marché", level=2)
    document.add_paragraph("Châssis aluminium à rupture de pont thermique.")
    document.add_paragraph().add_run("Clause en gras").bold = True
    tableau = document.add_table(rows=2, cols=3)
    for rangee, valeurs in zip(tableau.rows, (["N°", "Désignation", "U"], ["8.1", "Fenêtre", "u"])):
        for cellule, valeur in zip(rangee.cells, valeurs):
            cellule.text = valeur
    flux = io.BytesIO()
    document.save(flux)
    return flux.getvalue()


def _xlsx_ordinaire() -> bytes:
    from openpyxl import Workbook

    classeur = Workbook()
    feuille = classeur.active
    feuille.title = "DPGF"
    feuille.append(["N°", "Désignation", "U", "Qté", "PU HT", "Date", "Option"])
    feuille.append(["8.1", "Châssis aluminium", "u", 12, 850.5, datetime.datetime(2026, 11, 10, 14, 30), True])
    feuille.append(["8.2", "Porte-fenêtre", "u", None, 1200, datetime.date(2026, 12, 1), False])
    classeur.create_sheet("Annexe").append(["Remise", -0.05])
    flux = io.BytesIO()
    classeur.save(flux)
    return flux.getvalue()


# --- Tests ----------------------------------------------------------------------------------------------


class LectureDirecteTests(SimpleTestCase):
    def test_pages_pdf_liberees_une_a_une(self):
        # Sans page.close(), pdfplumber garde chaque page lue (environ 10 Mo par page de texte dense).
        import pdfplumber.page

        dossier = Path(tempfile.mkdtemp(prefix="lecture-directe-tests-"))
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        chemin = dossier / "cctp.pdf"
        lots = ["Gros oeuvre", "Charpente", "Couverture", "Menuiseries", "Platrerie", "Electricite", "Plomberie",
                "Chauffage", "Carrelage", "Peinture", "Serrurerie", "Facades"]
        chemin.write_bytes(pdf_pages([[f"Lot {lot}", f"Prescriptions du lot {lot.lower()}"] for lot in lots]))
        lire, fermer, evenements = pdfplumber.page.Page.extract_text, pdfplumber.page.Page.close, []

        def lire_trace(page, *args, **kwargs):
            evenements.append(("lue", page.page_number))
            return lire(page, *args, **kwargs)

        def fermer_trace(page):
            evenements.append(("libérée", page.page_number))
            return fermer(page)

        with mock.patch.object(pdfplumber.page.Page, "extract_text", autospec=True, side_effect=lire_trace), \
                mock.patch.object(pdfplumber.page.Page, "close", autospec=True, side_effect=fermer_trace):
            contenu = lire_document_direct(chemin, dossier)
        # Chaque page est libérée avant de lire la suivante (pdfplumber les libère encore toutes en fin de lecture).
        self.assertEqual(evenements[:24], [(etat, n) for n in range(1, 13) for etat in ("lue", "libérée")])
        texte = "\n".join(bloc.texte for bloc in contenu.blocs)
        self.assertIn("Lot Gros oeuvre", texte)
        self.assertIn("Prescriptions du lot facades", texte)

    def test_lecture_directe_pendant_les_tests(self):
        self.assertFalse(settings.LECTURE_ISOLEE)
        dossier = Path(tempfile.mkdtemp(prefix="lecture-directe-tests-"))
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        (dossier / "cctp.docx").write_bytes(_docx_ordinaire())
        with mock.patch("subprocess.Popen") as lancer:
            self.assertTrue(lire_document(dossier / "cctp.docx", dossier).blocs)
        lancer.assert_not_called()


@override_settings(LECTURE_ISOLEE=True, LECTURE_MEMOIRE_MAX_MO=2048, LECTURE_DELAI_MAX=120)
class LectureIsoleeTests(SimpleTestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix="lecture-isolee-tests-"))
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)

    def fichier(self, nom: str, contenu: bytes) -> Path:
        chemin = self.dossier / nom
        chemin.write_bytes(contenu)
        return chemin

    def test_fichiers_ordinaires_lus_a_l_identique(self):
        fichiers = [
            self.fichier("cctp.docx", _docx_ordinaire()),
            self.fichier("dpgf.xlsx", _xlsx_ordinaire()),
            self.fichier("dpgf.csv", "N°;Désignation;PU HT\n8.1;Châssis aluminium;850,50\n".encode("cp1252")),
            self.fichier("offre.pdf", pdf_texte(["Lot 08 Menuiseries", "Total HT 12 500,00"])),
        ]
        for chemin in fichiers:
            for tableaux_pdf in (False, True):
                attendu = lire_document_direct(chemin, self.dossier, tableaux_pdf=tableaux_pdf)
                # Rien n'est lu dans ce processus : seul l'enfant appelle lire_document_direct.
                with mock.patch.object(lecture, "lire_document_direct", side_effect=AssertionError("lu dans le parent")):
                    lu = lire_document(chemin, self.dossier, tableaux_pdf=tableaux_pdf)
                self.assertEqual(lu, attendu, chemin.name)
        self.assertEqual(lu.blocs[0].texte, "Lot 08 Menuiseries")
        classeur = lire_document(fichiers[1], self.dossier).tableaux
        self.assertEqual(classeur[0].lignes[1][5], datetime.datetime(2026, 11, 10, 14, 30))
        self.assertEqual([t.titre for t in classeur], ["DPGF", "Annexe"])
        self.assertEqual(list(self.dossier.glob("lecture-isolee-*")), [])  # fichiers d'échange supprimés

    def test_lecture_meme_si_sigchld_est_ignore(self):
        # Processus qui ignore SIGCHLD : le noyau récolte l'enfant de lui-même, waitid échoue (ECHILD).
        chemin = self.fichier("cctp.docx", _docx_ordinaire())
        ancien = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
        try:
            self.assertEqual(lire_document(chemin, self.dossier), lire_document_direct(chemin, self.dossier))
            with self.assertRaises(LimiteDepassee):
                executer_isole("bibliotheque.tests_isolation:calculer_sans_fin", delai=2, cpu=60)
        finally:
            signal.signal(signal.SIGCHLD, ancien)

    def test_exceptions_metier_retransmises_telles_quelles(self):
        for chemin, classe, message in (
            (self.fichier("notes.txt", b"texte"), FormatNonAnalyse, "Format .txt non pris en charge."),
            (self.fichier("abime.docx", b"PK\x03\x04 pas une archive"), ErreurLecture,
             "Fichier illisible : il est peut-être protégé par un mot de passe ou endommagé."),
            (self.fichier("vide.pdf", pdf_texte([])), FormatNonAnalyse, "Aucun texte lisible dans ce PDF."),
        ):
            with self.assertRaises(classe) as contexte:
                lire_document(chemin, self.dossier)
            self.assertIs(type(contexte.exception), classe)
            self.assertEqual(str(contexte.exception), message)

    @override_settings(LECTURE_MEMOIRE_MAX_MO=768)
    def test_pdf_page_geante_sans_garde_fou_arretee_par_le_plafond(self):
        # Garde-fou des pixels retiré dans l'enfant (comme un piège qu'aucun garde-fou ne connaît) : la page de
        # 200 × 200 pouces est rendue à 300 dpi, 60 000 × 60 000 pixels, 14 Go demandés d'un coup.
        chemin = self.fichier("offre.pdf", pdf_page_geante())
        debut = time.monotonic()
        with self.assertRaises(ErreurLecture) as contexte:
            lire_isole("bibliotheque.tests_isolation:lire_sans_plafond_de_pixels", chemin, self.dossier)
        self.assertIsInstance(contexte.exception, LectureInterrompue)
        self.assertEqual(str(contexte.exception), MESSAGE_LECTURE_INTERROMPUE)
        self.assertLess(time.monotonic() - debut, 60)
        # Un PDF ordinaire est lu sous le même plafond.
        ordinaire = self.fichier("ordinaire.pdf", pdf_texte(["Lot 08 Menuiseries"]))
        self.assertEqual(lire_document(ordinaire, self.dossier).blocs[0].texte, "Lot 08 Menuiseries")

    @override_settings(LECTURE_MEMOIRE_MAX_MO=768)
    def test_docx_grid_span_demesure_arrete_par_le_plafond(self):
        # Lecture des tableaux d'avant (_Row.cells, garde-fou absent) : la cellule est répétée 10**12 fois et la
        # mémoire croît sans fin. Arrêtée par le plafond de l'enfant ; la lecture actuelle n'y passe plus.
        chemin = self.fichier("offre.docx", docx_cellule(10**12))
        debut = time.monotonic()
        with self.assertRaises(ErreurLecture) as contexte:
            lire_isole("bibliotheque.tests_isolation:lire_avec_ancien_tableau_docx", chemin, self.dossier)
        self.assertIsInstance(contexte.exception, LectureInterrompue)
        self.assertEqual(str(contexte.exception), MESSAGE_LECTURE_INTERROMPUE)
        self.assertLess(time.monotonic() - debut, 120)
        self.assertEqual([b.lignes for b in lire_document(chemin, self.dossier).blocs if b.genre == "tableau"], [[["Prix"]]])

    def test_delai_depasse_arrete_l_enfant_et_ses_processus(self):
        fichier_pid = self.dossier / "petit-enfant.pid"
        debut = time.monotonic()
        with self.assertRaises(LimiteDepassee):
            executer_isole("bibliotheque.tests_isolation:attendre_un_petit_enfant", str(fichier_pid), delai=3, cpu=60)
        self.assertLess(time.monotonic() - debut, 15)
        # « sleep 300 » tué avec l'enfant (même groupe de processus) : disparu, ou zombie en attente d'init.
        statut = Path(f"/proc/{int(fichier_pid.read_text())}/stat")
        for _ in range(50):
            if not statut.exists() or statut.read_text().rpartition(")")[2].split()[0] in ("Z", "X"):
                break
            time.sleep(0.1)
        else:
            self.fail("processus lancé par l'enfant toujours vivant")

    def test_temps_de_calcul_plafonne(self):
        debut = time.monotonic()
        with self.assertRaisesMessage(LimiteDepassee, "SIGXCPU"):
            executer_isole("bibliotheque.tests_isolation:calculer_sans_fin", delai=60, cpu=1)
        self.assertLess(time.monotonic() - debut, 30)

    def test_enfant_tue_ou_exception_inattendue(self):
        with self.assertRaisesMessage(LimiteDepassee, "SIGKILL"):
            executer_isole("bibliotheque.tests_isolation:mourir_tue")
        chemin = self.fichier("cctp.docx", _docx_ordinaire())
        with self.assertRaises(ErreurLecture) as contexte, self.assertLogs("bibliotheque.lecture_isolee", "ERROR"):
            lire_isole("bibliotheque.tests_isolation:lever_une_exception_inattendue", chemin, self.dossier)
        self.assertIs(type(contexte.exception), ErreurLecture)
        self.assertEqual(str(contexte.exception), "Lecture impossible (KeyError) : le fichier est peut-être protégé ou endommagé.")
        self.assertIsInstance(contexte.exception.__cause__, ErreurEnfant)
        # Erreur quelconque après avoir pris plus de la moitié du plafond : c'est le plafond qui a été atteint.
        with self.assertRaisesMessage(LimiteDepassee, "mémoire"):
            executer_isole("bibliotheque.tests_isolation:remplir_puis_echouer", 400, memoire_mo=768)

    def test_sortie_d_erreur_lue_au_fil_de_l_eau_sans_remplir_le_disque(self):
        # 200 Mo d'avertissements : lus au fil de l'eau, seule la fin est gardée pour le journal.
        with self.assertLogs("bibliotheque.lecture_isolee", "WARNING") as journaux, self.assertRaises(LimiteDepassee):
            executer_isole("bibliotheque.tests_isolation:bavarder_puis_mourir", 200, dossier=self.dossier)
        self.assertIn("dernier message", journaux.output[0])
        self.assertLess(len(journaux.output[0]), 6000)
        self.assertEqual(list(self.dossier.iterdir()), [])  # rien d'écrit sur le disque

    def test_sockets_libreoffice_orphelins_retires(self):
        import socket
        import threading

        from .lecture_isolee import _retirer_sockets_orphelins

        prefixe = f"/tmp/OSL_PIPE_{os.getuid()}_SingleOfficeIPC_test{os.getpid()}"
        orphelin, mourant, actif = (Path(prefixe + nom) for nom in ("orphelin", "mourant", "actif"))
        prises = []
        for chemin in (orphelin, mourant, actif):
            prise = socket.socket(socket.AF_UNIX)
            prise.bind(str(chemin))
            prise.listen()
            prises.append(prise)
            self.addCleanup(chemin.unlink, missing_ok=True)
            self.addCleanup(prise.close)
        prises[0].close()  # le fichier reste, plus personne n'écoute
        threading.Timer(0.5, prises[1].close).start()  # LibreOffice tué, pas encore tout à fait arrêté
        _retirer_sockets_orphelins({str(orphelin), str(mourant), str(actif)}, attente=2)
        self.assertFalse(orphelin.exists())
        self.assertFalse(mourant.exists())
        self.assertTrue(actif.exists())  # une autre conversion en cours

    def test_resultat_relu_sans_objet_inattendu(self):
        with self.assertRaises(pickle.UnpicklingError):
            executer_isole("bibliotheque.tests_isolation:rendre_un_objet_inattendu")
