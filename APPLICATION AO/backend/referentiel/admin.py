from django import forms
from django.contrib import admin

from .codes import code_normalise, verifier_code
from .models import Lot


class LotAdminForm(forms.ModelForm):
    """Mêmes règles que l'écran « Lots proposés » de l'application : format du numéro, pas de « 3 » à côté de « 03 »."""

    class Meta:
        model = Lot
        fields = "__all__"

    def clean_code(self):
        code = self.cleaned_data["code"]
        if self.instance.pk is None or code.strip() != self.instance.code:
            try:
                code = verifier_code(code)
            except ValueError as exc:
                raise forms.ValidationError(str(exc)) from None
        doublon = next((l for l in Lot.objects.exclude(pk=self.instance.pk) if code_normalise(l.code) == code_normalise(code)), None)
        if doublon is not None:
            raise forms.ValidationError(f"Le numéro {code} est déjà celui du lot {doublon}.")
        return code


@admin.register(Lot)
class LotAdmin(admin.ModelAdmin):
    """Plus simple depuis l'application : Projets › Nouveau projet › « Modifier la liste des lots proposés »."""

    form = LotAdminForm
    list_display = ("code", "intitule", "propose", "actif")
    list_editable = ("intitule", "propose", "actif")
    list_filter = ("actif", "propose")
    search_fields = ("code", "intitule")
    # Ordre recalculé d'après le numéro à chaque enregistrement.
    readonly_fields = ("ordre",)

    def save_model(self, request, obj, form, change):
        from .api import reordonner_catalogue

        super().save_model(request, obj, form, change)
        reordonner_catalogue()
        if change and "code" in form.changed_data:
            # Les passages de l'assistant citent le numéro du lot : index remis à jour.
            from assistant.tasks import planifier_indexation

            planifier_indexation()
