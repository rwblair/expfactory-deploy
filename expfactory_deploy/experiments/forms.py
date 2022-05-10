from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Layout, Submit
from django import forms
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.forms import (
    BaseFormSet,
    ModelForm,
    inlineformset_factory,
    modelformset_factory,
)
from django.urls import reverse_lazy
from taggit.forms import TagField
import git
import pathlib
from giturlparse import parse
from experiments import models as models

class RepoOriginForm(ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.add_input(Submit('submit', 'Submit'))

    class Meta:
        model  = models.RepoOrigin
        fields = ["url"]
        widgets = {
            "url": forms.TextInput(),
        }

    # Todo: extract user/org name and use them in path and name 
    # could also imagine adding index for collisions.
    def clean(self):
        cleaned_data = super().clean()
        url = cleaned_data["url"]
        gitparse_url = parse(url)
        if not gitparse_url.valid:
            self.add_error("url", "gitparseurl library could not validate repo url.")
        else:
            name = gitparse_url.name
            path = pathlib.Path(settings.REPO_DIR, name)
            path.mkdir(parents=True, exist_ok=True)
            self.instance.path = path
            self.instance.name = name
            try:
                models.RepoOrigin.objects.get(name=name, path=path)
            except ObjectDoesNotExist:
                pass
            else:
                self.add_error('Repository with this name currently exists')
        return cleaned_data

'''
    Here we make a widget and field to make partial use of form validation
    for the checkboxes that are manually rendered in subject-list.
    Exposing instance and relation data in a nice table takes more work
    with custom widget templates. In lieu of that we manually render the
    inputs in the template, and keep our feel bad hacks small.
'''
class NoRenderWidget(forms.SelectMultiple):
    def render(*args, **kwargs):
        return ""

'''
    TypedMultipleChoiceField understands the arrays that html post
    data sends in, but it expects 'valid_values' to be pre specified
    a la choices tupoles. We bypass this check with the valid_value override.
    Validate is still called, which attempts to coerce the values.
'''
class IdList(forms.TypedMultipleChoiceField):
    def __init__(self, *args, **kwargs):
        self.coerce = int
        super().__init__(*args, **kwargs)

    def valid_value(self, value):
        return True

class SubjectActionForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.add_input(Submit('deactivate', 'Deactivate', formaction='/subjects/toggle'))
        self.helper.add_input(Submit('assign', 'Assign', formaction='/subjects/assign'))
        self.helper.form_tag = False

    batteries = forms.ModelMultipleChoiceField(
        queryset=models.Battery.objects.all(),
        widget=forms.CheckboxSelectMultiple, 
        required=False
    )
    subjects = IdList(
        widget=NoRenderWidget,
        required=False,
        label=False
    )


class SubjectCount(forms.Form):
    count = forms.IntegerField(required=True, label="Number of subjects to create")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.add_input(Submit('submit', 'Submit'))


class ExperimentRepoForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_tag = True
        self.helper.add_input(Submit('submit', 'Update'))

    class Meta:
        model = models.ExperimentRepo
        fields = ["name", "tags"]
        widgets = {
            "name": forms.TextInput()
        }

class ExperimentRepoBulkTagForm(forms.Form):
    tags = TagField()
    experiments = IdList(
        widget=NoRenderWidget,
        required=False,
        label=False
    )
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.add_input(
            Submit(
                'add_tags',
                'Add Tags',
                formaction=reverse_lazy("experiments:experiment-repo-bulk-tag-add")
            )
        )
        self.helper.add_input(
            Submit(
                'add_tags',
                'Add Tags',
                formaction=reverse_lazy("experiments:experiment-repo-bulk-tag-remove")
            )
        )
        self.helper.form_id = 'experiment-repo-bulk-tag'


class BatteryForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_tag = False

    class Meta:
        model = models.Battery
        fields = ["title", "consent", "instructions", "advertisement", "status", "public"]
        widgets = {
            "title": forms.TextInput(),
            "consent": forms.Textarea(attrs={"cols": 80, "rows": 2}),
            "instructions": forms.Textarea(attrs={"cols": 80, "rows": 2}),
            "advertisement": forms.Textarea(attrs={"cols": 80, "rows": 2}),
            "status": forms.HiddenInput(),
        }


class ExperimentInstanceForm(ModelForm):
    class Meta:
        model = models.ExperimentInstance
        fields = ["note", "commit", "experiment_repo_id"]
        widgets = {
            "commit": forms.TextInput(),
            "note": forms.Textarea(attrs={"cols": 40, "rows": 1}),
        }
    
    def save(self, commit=True):
        exp_instance, _ = models.ExperimentInstance.objects.update_or_create(
            commit=self.instance.commit,
            experiment_repo_id=self.instance.experiment_repo_id,
            defaults={'note': self.instance.note}
        )
        return exp_instance


class ExperimentInstanceOrderForm(ExperimentInstanceForm):
    exp_order = forms.IntegerField()
    battery_id = None

    def __init__(self, *args, **kwargs):
        ordering = kwargs.pop("ordering", None)
        self.battery_id = kwargs.pop("battery_id", None)
        super().__init__(*args, **kwargs)
        if ordering and self.instance.id:
            self.fields["exp_order"].initial = ordering.get(
                id=self.instance.id
            ).exp_order
        self.fields["commit"].initial = "latest"
        self.helper = FormHelper(self)
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Field("exp_order", css_class="exp-order-input"),
            Field("note", css_class="exp-note-input"),
            Field("commit", css_class="exp-commit-input"),
            Field("experiment_repo_id", css_class="exp-repo-input"),
        )

    def clean(self):
        cleaned_data = super().clean()
        commit = cleaned_data["commit"]
        exp_instance = cleaned_data["experiment_repo_id"]
        if commit == "latest":
            commit = exp_instance.get_latest_commit()

        # should we return gitpython error message here?
        if not exp_instance.origin.is_valid_commit(commit):
            raise forms.ValidationError(
                f"Commit '{commit}' is invalid for {exp_instance.url}"
            )

        cleaned_data["commit"] = commit
        return cleaned_data

    def save(self, *args, **kwargs):
        exp_instance = super().save(*args, **kwargs)
        exp_repo_id = exp_instance.experiment_repo_id_id
        battery = models.Battery.objects.get(id=self.battery_id)
        try:
            batt_exp = models.BatteryExperiments.objects.get(
                battery=battery, experiment_instance__experiment_repo_id=exp_repo_id
            )
            batt_exp.order = self.cleaned_data.get("exp_order", -1)
        except ObjectDoesNotExist:
            batt_exp = models.BatteryExperiments(
                battery=battery,
                experiment_instance=exp_instance,
                order=self.cleaned_data.get("exp_order", -1),
            )
        batt_exp.save()
        return exp_instance


ExpInstanceFormset = modelformset_factory(
    models.ExperimentInstance,
    form=ExperimentInstanceOrderForm,
    can_delete=True,
    extra=0,
)


