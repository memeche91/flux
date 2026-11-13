from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("referentiel", "0002_lots_par_defaut")]

    operations = [
        migrations.AddField(
            model_name="lot",
            name="propose",
            field=models.BooleanField(default=True, verbose_name="proposé à la création des projets"),
        ),
    ]
