import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UsernameField
from django.db.models.functions import Lower

from .models import Assessment, CatalogCategory, Company, Hazard, Probability


class LoginForm(AuthenticationForm):
    username = UsernameField(label="Email", widget=forms.EmailInput(attrs={"autocomplete": "username", "autofocus": True}))


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ("name",)


class AssessmentForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = ("title",)


class EditVersionForm(forms.Form):
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


class NonNegativeDecimalField(forms.DecimalField):
    widget = forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off"})

    def to_python(self, value):
        if value in self.empty_values:
            return None
        value = value.strip()
        if not value:
            return None
        if not re.fullmatch(r"[0-9]+(?:[,.][0-9]+)?", value):
            raise forms.ValidationError("Inserisci un numero non negativo. Puoi usare la virgola per i decimali.")
        value = value.replace(",", ".")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        return super().to_python(value)


class ProbabilityForm(EditVersionForm):
    def __init__(self, hazards, values, *args, **kwargs):
        super().__init__(*args, **kwargs)
        probability = Probability._meta.get_field("value")
        self.for_hazard = {}
        for hazard in hazards:
            name = f"p_{hazard.pk}"
            saved = values.get(hazard.pk, "")
            self.for_hazard[hazard.pk] = name
            self.fields[name] = NonNegativeDecimalField(
                label=hazard.name,
                required=False,
                max_digits=probability.max_digits,
                decimal_places=probability.decimal_places,
                initial=saved,
            )
            self.fields[name].widget.attrs["data-saved-value"] = saved

    def probabilities(self):
        return {hazard: self.cleaned_data[field] for hazard, field in self.for_hazard.items()}


class BulkForm(EditVersionForm):
    scope = forms.ChoiceField(choices=[("row", "Voce selezionata"), ("all", "Intera bozza")], initial="row")
    action = forms.ChoiceField(choices=[("zero", "Imposta a 0"), ("clear", "Svuota")])


class CategoryForm(EditVersionForm):
    name = forms.CharField(label="Nome della categoria", max_length=255)


class HazardSeverityForm(EditVersionForm):
    _severity = Hazard._meta.get_field("severity")
    severity = NonNegativeDecimalField(
        label="Gravità", max_digits=_severity.max_digits, decimal_places=_severity.decimal_places,
    )


class NewHazardForm(HazardSeverityForm):
    name = forms.CharField(label="Nome del pericolo", max_length=255)
    kind = forms.ChoiceField(label="Tipo di pericolo", choices=Hazard.Kind.choices)
    field_order = ["name", "kind", "severity"]


class CatalogRowForm(EditVersionForm):
    category = forms.ModelChoiceField(label="Categoria", queryset=CatalogCategory.objects.none())
    label = forms.CharField(label="Nome della sottocategoria", max_length=255)

    def __init__(self, catalog_version, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = catalog_version.categories.order_by(Lower("name"), "pk")
