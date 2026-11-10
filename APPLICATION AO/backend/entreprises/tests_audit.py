"""Audit global (constat 2) : import de l'annuaire protégé contre un classeur démesuré."""
import csv
import io
from unittest import mock

from django.test import TestCase

from bibliotheque import lecture
from bibliotheque.tests_audit import xlsx_chaines_partagees

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
        with mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 5_000), mock.patch("openpyxl.load_workbook") as chargement:
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
            mock.patch("openpyxl.load_workbook") as chargement,
            self.assertRaisesMessage(ImportImpossible, "anormalement volumineux"),
        ):
            _lignes("annuaire.xlsx", contenu)
        chargement.assert_not_called()

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
