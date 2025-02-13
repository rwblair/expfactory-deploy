import datetime
import os
import random
import uuid
from collections import defaultdict
from pathlib import Path

import git
import reversion
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.dispatch import receiver
from django.urls import reverse
from giturlparse import parse
from model_utils import Choices
from model_utils.fields import MonitorField, StatusField
from model_utils.models import StatusModel, TimeStampedModel
from taggit.managers import TaggableManager

from .utils import repo as repo
from users.models import Group

@reversion.register()
class Framework(models.Model):
    """ Framework used by experiments. """

    name = models.TextField(unique=True)
    template = models.TextField()


class FrameworkResource(models.Model):
    name = models.TextField(unique=True)
    path = models.TextField()


class SubjectTaskStatusModel(StatusModel):
    """Abstract class that tracks the various states a subject might
    be in relation to either an experiment or a battery"""

    STATUS = Choices("not-started", "started", "completed", "failed", "redo")
    status = StatusField(default="not-started")
    started_at = MonitorField(monitor="status", when=["started"], default=None, null=True)
    completed_at = MonitorField(monitor="status", when=["completed"], default=None, null=True)
    failed_at = MonitorField(monitor="status", when=["failed"], default=None, null=True)

    @property
    def completed(self):
        return self.status == self.STATUS.completed

    class Meta:
        abstract = True


class RepoOrigin(models.Model):
    """ Location of a repository that contains an experiment """

    url = models.TextField(unique=True)
    path = models.TextField(unique=True)
    name = models.TextField(blank=True, unique=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.url

    def get_latest_commit(self):
        return repo.get_latest_commit(self.path).hexsha

    def commit_date(self, commit=None):
        return repo.commit_date(self.path, commit)

    def is_valid_commit(self, commit):
        return repo.is_valid_commit(self.path, commit)

    def checkout_commit(self, commit):
        base_repo = git.Repo(self.path)
        stem = Path(self.path).stem
        deploy_to = str(Path(settings.DEPLOYMENT_DIR, stem, commit))
        if deploy_to in base_repo.git.worktree("list"):
            return deploy_to
        elif not repo.is_valid_commit(self.path, commit):
            return False
        else:
            base_repo.git.worktree("add", deploy_to, commit)
            return deploy_to

    def pull_origin(self):
        repo.pull_origin(self.path)
        self.update_dependents()

    def update_dependents(self):
        latest = self.get_latest_commit()
        instances = ExperimentInstance.objects.filter(experiment_repo_id__origin=self.id).exclude(commit=latest)
        # we will want to filter battexps on use_latest in production
        battexps = BatteryExperiments.objects.filter(experiment_instance__id__in=instances.values_list('id', flat=True))
        for battexp in battexps:
            new_instance, _ = ExperimentInstance.objects.get_or_create(experiment_repo_id=battexp.experiment_instance.experiment_repo_id, commit=latest)
            battexp.experiment_instance = new_instance
            battexp.save()

    def clone(self):
        os.makedirs(self.path, exist_ok=True)
        repo = git.Repo.clone_from(self.url, self.path)

    @property
    def display_url(self):
        if "git@github.com:" in self.url:
            return self.url.replace("git@github.com:", "https://github.com/")
        return self.url




''' Will likely want to have git clone be called as a task from here
@receiver(models.signals.post_save, sender=RepoOrigin)
def execute_after_save(sender, instance, created, *args, **kwargs):
    if created:
'''

@reversion.register()
class ExperimentRepo(models.Model):
    """ Location of an experiment and the repository it belongs to """

    name = models.TextField()
    origin = models.ForeignKey(RepoOrigin, null=True, on_delete=models.SET_NULL)
    branch = models.TextField(default="master")
    location = models.TextField()
    framework = models.ForeignKey(Framework, null=True, on_delete=models.SET_NULL)
    active = models.BooleanField(default=True)
    cogat_id = models.TextField(blank=True)
    tags = TaggableManager()

    def get_absolute_url(self):
        return reverse("experiments:experiment-repo-detail", kwargs={"pk": self.pk})

    """ We may want to just look at latest commit for files in its directory(location)
        instead of getting entire repos latest commit, case where exp removed from repo
        at some point. """

    def get_latest_commit(self):
        return self.origin.get_latest_commit()

    @property
    def url(self):
        base_path = self.origin.path
        exp_location = self.location
        if "git@github.com:" in self.origin.url:
            origin_url = self.origin.url.replace("git@github.com:", "https://github.com/")
            origin_url = origin_url.replace(".git", "")
            exp_location = self.location.replace(base_path, f"/tree/{self.branch}")
        else:
            origin_url = self.origin.url
        return f"{origin_url}{exp_location}"

    def __str__(self):
        return self.name


@reversion.register()
class ExperimentInstance(models.Model):
    """ A specific point in time of an experiment. """

    note = models.TextField(blank=True)
    commit = models.TextField(blank=True)
    commit_date = models.DateField(blank=True, null=True)
    experiment_repo_id = models.ForeignKey(ExperimentRepo, on_delete=models.CASCADE)

    @property
    def remote_url(self):
        url = self.experiment_repo_id.url
        url = url.replace(self.experiment_repo_id.branch, self.commit)
        return url

    def is_valid_commit(self):
        return self.experiment_repo_id.origin.is_valid_commit(self.commit)

    def deploy_static(self):
        return self.experiment_repo_id.origin.checkout_commit(self.commit)

    def __str__(self):
        return f"{self.commit}"


@reversion.register()
class Battery(TimeStampedModel, StatusField):
    """when a battery is "created" its a template.
    When cloned for it becomes a draft for deployment
    When published no further changes are allowed.
    Finally inactive prevents subjects from using it.
    """

    STATUS = Choices("template", "draft", "published", "inactive")
    status = StatusField()
    title = models.TextField()
    template_id = models.ForeignKey(
        "Battery", on_delete=models.CASCADE, blank=True, null=True,
        related_name="children"
    )
    experiment_instances = models.ManyToManyField(
        ExperimentInstance, through="BatteryExperiments"
    )
    consent = models.TextField(blank=True)
    instructions = models.TextField(blank=True)
    advertisement = models.TextField(blank=True)
    random_order = models.BooleanField(default=True)
    public = models.BooleanField(default=False)
    inter_task_break = models.DurationField(default=datetime.timedelta())
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, null=True)

    def duplicate(self, status='draft'):
        """ passing object we wish to clone through model constructor allows
        created field to be properly set
        """
        new_batt = Battery.objects.get(id=self.id)
        new_batt.pk = None
        new_batt.id = None
        if self.template_id is None:
            new_batt.template_id = self
        new_batt.status = status
        new_batt.created = datetime.datetime.now()
        new_batt.save()
        for batt_exp in list(self.batteryexperiments_set.all()):
            batt_exp.battery = new_batt
            batt_exp.pk = None
            batt_exp.id = None
            batt_exp.save()
        return new_batt


class BatteryExperiments(models.Model):
    """ Associate specific experiments with a deployment of a battery """

    experiment_instance = models.ForeignKey(
        ExperimentInstance, on_delete=models.CASCADE
    )
    battery = models.ForeignKey(Battery, on_delete=models.CASCADE)
    order = models.IntegerField(
        default=0,
        verbose_name="Experiment order",
    )
    use_latest = models.BooleanField(default=True)

    class Meta:
        # should order by battery_id then order, to group things properly?
        ordering = ('order',)



class Subject(models.Model):
    handle = models.TextField(blank=True)
    email = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True)
    active = models.BooleanField(default=True)
    prolific_id = models.TextField(unique=True, blank=True, null=True, default=None)
    tags = TaggableManager()

    def __str__(self):
        if self.handle:
            return f"{self.handle}"
        return f"{self.uuid}"


class Result(TimeStampedModel, SubjectTaskStatusModel):
    """ Results from a particular experiment returned by subjects """
    assignment = models.ForeignKey(
        'Assignment', on_delete=models.SET_NULL, null=True
    )
    battery_experiment = models.ForeignKey(
        BatteryExperiments, on_delete=models.SET_NULL, null=True
    )
    # in case we want to collect results without an assignment
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, null=True)
    data = models.TextField(blank=True)


class Assignment(SubjectTaskStatusModel):
    """ Associate a subject with a battery deployment that they should complete """
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    battery = models.ForeignKey(Battery, on_delete=models.CASCADE)
    consent_accepted = models.BooleanField(null=True)
    note = models.TextField(blank=True)
    ordering = models.ForeignKey('ExperimentOrder', on_delete=models.SET_NULL, blank=True, null=True)
    # index that can be used to divy cohort up by as experiment sees fit.
    group_index = models.IntegerField(default=0)

    @property
    def results(self):
        return self.result_set.all()

    ''' does not account for redos '''
    @property
    def result_status(self):
        results = self.results
        status = defaultdict(lambda: 0)
        status['total'] = len(results)
        for result in results:
            status[result.status] += 1
        return status

    def save(self, *args, **kwargs):
        if self.pk == None and self.battery.random_order:
            self.ordering = ExperimentOrder.objects.create(battery=self.battery)
            self.ordering.generate_order_items()
        super().save(*args, **kwargs)

    def get_next_experiment(self):
        if self.ordering == None:
            order = "?" if self.battery.random_order else "order"
            batt_exps = (
                BatteryExperiments.objects.filter(battery=self.battery)
                .select_related("experiment_instance")
                .order_by(order)
            )
        else:
            batt_exps = self.ordering.experimentorderitem_set.all().order_by("order")
        experiments = [x.experiment_instance for x in batt_exps]
        exempt = list(
            Result.objects.filter(
                Q(status=Result.STATUS.completed) | Q(status=Result.STATUS.failed),
                subject=self.subject,
            ).values_list('battery_experiment__experiment_instance', flat=True)
        )
        unfinished = [exp for exp in experiments if exp.id not in exempt]
        if len(unfinished):
            if self.status == "not-started":
                self.status = "started"
                self.save()
            return unfinished[0], len(unfinished)
        else:
            self.status = "completed"
            self.save()
            return None, 0

    class Meta:
        constraints = [
            models.UniqueConstraint(
                name="unique_assignment", fields=["subject", "battery"]
            )
        ]

class ExperimentOrderItem(models.Model):
    battery_experiment = models.ForeignKey(
        BatteryExperiments, on_delete=models.CASCADE
    )
    experiment_order = models.ForeignKey('ExperimentOrder', on_delete=models.CASCADE)
    order = models.IntegerField(
        default=0,
        verbose_name="Experiment order",
    )


class ExperimentOrder(models.Model):
    """
    This model allows us to maintain multiple experiment orderings for a battery.
    It also allows us to generate the random order of experiments for an assignment at
    assignment creation time.
    """
    name = models.TextField(blank=True)
    battery = models.ForeignKey(Battery, on_delete=models.CASCADE)
    auto_generated = models.BooleanField(default=True)

    def generate_order_items(self):
        experiments = list(BatteryExperiments.objects.filter(battery=self.battery).values_list('id', flat=True))
        random.shuffle(experiments)
        order_items = []
        for index, exp in enumerate(experiments):
            order_items.append(ExperimentOrderItem(battery_experiment_id=exp, experiment_order=self, order=index))
        ExperimentOrderItems.bulk_create(order_items)

