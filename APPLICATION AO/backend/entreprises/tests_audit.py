"""Audit global (constat 2) : import de l'annuaire protégé contre un classeur démesuré."""
import csv
import io
from unittest import mock

from django.test import TestCase, override_settings

from bibliotheque import lecture
from bibliotheque.tests_audit import (
    xlsx_chaines_partagees,
    xlsx_graphique_et_liens_externes,
)

from . import importation
from .importation import ImportImpossible, _lignes, importer


def _classeur(lignes: list[list], vides_avant_fin: int = 0) -> bytes:
    from openpyxl import Workbook

    classeur = Workbook()
    feuille = classeur.active
    for ligne in lignes:
        feuille.append(ligne)
    if vides_avant_fin:
        # Feuille « formatée » très loin : cellules sans valeur, mais avec un style.
        feuille.cell(len(lignes) + vides_avant_fin, 1).number_format = "0.00"
    flux = io.BytesIO()
    classeur.save(flux)
    return flux.getvalue()


class ImportAnnuaireAuditTests(TestCase):
    def test_classeur_ordinaire_importe(self):
        contenu = _classeur([["Entreprise", "Ville"], ["Menuiseries Durand", "Annecy"]], vides_avant_fin=5_000)
        lignes = _lignes("annuaire.xlsx", contenu)
        self.assertLessEqual(len(lignes), 2 + importation.LIGNES_VIDES_MAX + 1)  # le blanc final n'est pas chargé
        self.assertEqual(importer("annuaire.xlsx", contenu).creees, 1)

    def test_table_des_chaines_demesuree_refusee(self):
        contenu = xlsx_chaines_partagees([["Entreprise", "Ville"]] + [[f"Entreprise {n}", f"Ville {n}"] for n in range(300)])
        self.assertEqual(len(_lignes("annuaire.xlsx", contenu)), 301)
        with mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 5_000), mock.patch.object(lecture, "ouvrir_classeur") as chargement:
            with self.assertRaisesMessage(ImportImpossible, "anormalement volumineux"):
                _lignes("annuaire.xlsx", contenu)
        chargement.assert_not_called()

    def test_classeur_tres_large_borne(self):
        # Dimension déclarée sur 16 384 colonnes : openpyxl compléterait chaque ligne à 16 384 cellules.
        contenu = xlsx_chaines_partagees(
            [["Entreprise", "Ville"]] + [[f"Entreprise {n}", "Annecy"] for n in range(300)], dimension="A1:XFD301"
        )
        lignes = _lignes("annuaire.xlsx", contenu)
        self.assertEqual(len(lignes), 301)
        self.assertLessEqual(max(len(ligne) for ligne in lignes), importation.COLONNES_MAX)
        self.assertEqual(importer("annuaire.xlsx", contenu).creees, 300)

    def test_trop_de_lignes_refuse(self):
        contenu = _classeur([["Entreprise", "Ville"]] + [[f"Entreprise {n}", "Annecy"] for n in range(60)])
        with mock.patch.object(importation, "LIGNES_MAX", 50), self.assertRaisesMessage(ImportImpossible, "trop long"):
            _lignes("annuaire.xlsx", contenu)

    def test_classeur_demesure_une_fois_decompresse_refuse_sans_etre_lu(self):
        # L'import tourne dans le serveur web, sans limite de mémoire : toute l'archive est bornée.
        contenu = _classeur([["Entreprise", "Ville"]] + [[f"Entreprise {n}", "Annecy"] for n in range(300)])
        self.assertEqual(len(_lignes("annuaire.xlsx", contenu)), 301)
        with (
            mock.patch.object(importation, "ANNUAIRE_DECOMPRESSE_MAX", 10_000),
            mock.patch.object(lecture, "ouvrir_classeur") as chargement,
            self.assertRaisesMessage(ImportImpossible, "anormalement volumineux"),
        ):
            _lignes("annuaire.xlsx", contenu)
        chargement.assert_not_called()

    def test_liens_externes_et_feuilles_de_graphique_jamais_lus(self):
        # L'import tourne dans le serveur web, sans limite de mémoire : un lien externe de 20 Mo cité dix fois
        # (fichier de 52 Ko) faisait monter gunicorn de 2 Go en 70 s. Ni liens externes ni graphiques ne sont lus.
        from openpyxl.reader import drawings, workbook

        contenu = xlsx_graphique_et_liens_externes(citations=2, cadres=2, references=3)
        with mock.patch.object(workbook, "read_external_link") as liens_externes, mock.patch.object(drawings, "read_chart") as graphiques:
            lignes = _lignes("annuaire.xlsx", contenu)
        liens_externes.assert_not_called()
        graphiques.assert_not_called()
        self.assertEqual(lignes, [["N°", "Désignation", "PU HT"], ["8.1", "Châssis aluminium", "850"]])

    def test_csv_trop_long_refuse(self):
        contenu = "\n".join(["Entreprise;Ville"] + [f"Entreprise {n};Annecy" for n in range(60)]).encode()
        self.assertEqual(len(_lignes("annuaire.csv", contenu)), 61)
        with mock.patch.object(importation, "LIGNES_MAX", 50), self.assertRaisesMessage(ImportImpossible, "trop long"):
            _lignes("annuaire.csv", contenu)

    def test_csv_tres_large_borne(self):
        contenu = ("Entreprise;Ville" + ";" * 5_000 + "\nMenuiseries Durand;Annecy\n").encode()
        lignes = _lignes("annuaire.csv", contenu)
        self.assertLessEqual(max(len(ligne) for ligne in lignes), importation.COLONNES_MAX)
        self.assertEqual(importer("annuaire.csv", contenu).creees, 1)

    def test_csv_guillemet_non_referme_refuse_proprement(self):
        # Champ ouvert par un guillemet jamais refermé : le module csv dépasse sa limite de taille de champ.
        contenu = ('Entreprise;Ville\n"Menuiseries Durand;Annecy\n' + "x" * 200_000).encode()
        with self.assertRaisesMessage(ImportImpossible, "CSV illisible"):
            _lignes("annuaire.csv", contenu)

    def test_echec_de_la_detection_du_separateur_sans_effet_sur_csv_excel(self):
        _lignes("annuaire.csv", b"Entreprise\nMenuiseries Durand\n")  # une colonne : séparateur introuvable
        self.assertEqual(csv.excel.delimiter, ",")


class ImportAnnuaireIsoleTests(TestCase):
    """Classeur lu dans un processus séparé et plafonné (forcé ici : lecture directe pendant les tests)."""

    def test_classeur_lu_a_l_identique_dans_un_processus_separe(self):
        contenu = _classeur([["Entreprise", "Ville", "Créée le"], ["Menuiseries Durand", "Annecy", 1998], ["Plâtres Martin", "Cran", None]])
        attendu = importation.lignes_classeur(contenu)
        with override_settings(LECTURE_ISOLEE=True), mock.patch.object(
            importation, "lignes_classeur", side_effect=AssertionError("lu dans le serveur web")
        ):
            self.assertEqual(_lignes("annuaire.xlsx", contenu), attendu)
            self.assertEqual(importer("annuaire.xlsx", contenu).creees, 2)
            # Exception métier de l'enfant retransmise telle quelle.
            with self.assertRaisesMessage(ImportImpossible, importation.CLASSEUR_ILLISIBLE):
                _lignes("annuaire.xlsx", b"PK\x03\x04 pas une archive")

    def test_plafond_atteint_refuse_proprement(self):
        contenu = _classeur([["Entreprise", "Ville"], ["Menuiseries Durand", "Annecy"]])
        with override_settings(LECTURE_ISOLEE=True, LECTURE_MEMOIRE_MAX_MO=1):  # même Django ne se charge pas
            with self.assertRaisesMessage(ImportImpossible, importation.LECTURE_INTERROMPUE):
                _lignes("annuaire.xlsx", contenu)

    def test_texte_demesure_refuse(self):
        # Chaîne partagée citée par toutes les lignes : chaque ligne importée la reprendrait (lots, notes).
        contenu = _classeur([["Entreprise", "Notes"]] + [[f"Entreprise {n}", "x" * 100] for n in range(50)])
        self.assertEqual(len(_lignes("annuaire.xlsx", contenu)), 51)
        with mock.patch.object(importation, "ANNUAIRE_CARACTERES_MAX", 2_000), self.assertRaisesMessage(ImportImpossible, "anormalement volumineux"):
            _lignes("annuaire.xlsx", contenu)
