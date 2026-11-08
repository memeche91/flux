"""Nomenclature de lots proposée au premier démarrage.

Elle se modifie ensuite librement dans l'administration (/admin) : ajout,
renommage, changement d'ordre ou désactivation d'un lot.
"""
from django.db import migrations

LOTS_PAR_DEFAUT = [
    ("TCE", "Tous corps d'état (document multi-lots)"),
    ("00", "Prescriptions communes à tous les lots"),
    ("01", "Désamiantage – Démolitions"),
    ("02", "Terrassements – VRD"),
    ("03", "Gros œuvre – Maçonnerie"),
    ("04", "Charpente – Ossature bois"),
    ("05", "Couverture – Zinguerie"),
    ("06", "Étanchéité"),
    ("07", "Façades – Ravalement – ITE"),
    ("08", "Menuiseries extérieures"),
    ("09", "Serrurerie – Métallerie"),
    ("10", "Menuiseries intérieures"),
    ("11", "Plâtrerie – Cloisons – Faux plafonds"),
    ("12", "Revêtements de sols durs – Faïence"),
    ("13", "Revêtements de sols souples"),
    ("14", "Peinture – Revêtements muraux"),
    ("15", "Plomberie – Sanitaires"),
    ("16", "Chauffage – Ventilation – Climatisation"),
    ("17", "Électricité – Courants forts et faibles"),
    ("18", "Ascenseurs"),
    ("19", "Espaces verts – Aménagements extérieurs"),
]


def creer_lots(apps, schema_editor):
    Lot = apps.get_model("referentiel", "Lot")
    for ordre, (code, intitule) in enumerate(LOTS_PAR_DEFAUT):
        Lot.objects.get_or_create(code=code, defaults={"intitule": intitule, "ordre": ordre * 10})


class Migration(migrations.Migration):
    dependencies = [("referentiel", "0001_initial")]

    operations = [migrations.RunPython(creer_lots, migrations.RunPython.noop)]
