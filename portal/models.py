import uuid

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class Company(models.Model):
    name = models.CharField("ragione sociale", max_length=255)

    class Meta:
        ordering = ["name", "pk"]
        verbose_name = "azienda"
        verbose_name_plural = "aziende"

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **fields):
        if not email:
            raise ValueError("L'indirizzo email è obbligatorio.")
        user = self.model(email=email.strip().lower(), **fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **fields):
        fields.setdefault("is_staff", False)
        fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **fields)

    def create_superuser(self, email, password=None, **fields):
        fields.setdefault("is_staff", True)
        fields.setdefault("is_superuser", True)
        if not fields["is_staff"] or not fields["is_superuser"]:
            raise ValueError("L'amministratore deve avere entrambi i permessi di sistema.")
        return self._create_user(email, password, **fields)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username.strip())


class User(AbstractUser):
    username = None
    email = models.EmailField("email", unique=True)
    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, null=True, blank=True, verbose_name="azienda cliente"
    )
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta:
        verbose_name = "utente"
        verbose_name_plural = "utenti"
        constraints = [models.UniqueConstraint(Lower("email"), name="user_unique_email_lower")]


class CatalogVersion(models.Model):
    number = models.PositiveIntegerField(unique=True)
    published_at = models.DateTimeField(null=True, blank=True)
    edit_version = models.PositiveIntegerField(default=0)


class Catalog(models.Model):
    # A single row coordinates publication and draft edits.
    current = models.ForeignKey(
        CatalogVersion, on_delete=models.PROTECT, null=True, related_name="+"
    )
    draft = models.ForeignKey(
        CatalogVersion, on_delete=models.PROTECT, null=True, related_name="+"
    )


class CatalogCategory(models.Model):
    version = models.ForeignKey(CatalogVersion, on_delete=models.PROTECT, related_name="categories")
    key = models.UUIDField(default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["version", "key"], name="category_key_per_version"),
            models.UniqueConstraint(Lower("name"), "version", name="category_name_per_version"),
        ]

    def __str__(self):
        return self.name


class CatalogRow(models.Model):
    category = models.ForeignKey(CatalogCategory, on_delete=models.PROTECT, related_name="rows")
    key = models.UUIDField(default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=255, blank=True)  # Empty label is the general entry.
    intended_use = models.CharField(max_length=255, blank=True)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["position", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["category", "key"], name="row_key_per_category"),
            models.UniqueConstraint(Lower("label"), "category", name="row_label_per_category"),
        ]


class Hazard(models.Model):
    class Kind(models.TextChoices):
        CHEMICAL = "C", "Chimico"
        PHYSICAL = "F", "Fisico"
        BIOLOGICAL = "B", "Biologico"

    version = models.ForeignKey(CatalogVersion, on_delete=models.PROTECT, related_name="hazards")
    key = models.UUIDField(default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=1, choices=Kind)
    severity = models.DecimalField(max_digits=12, decimal_places=6)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["position", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["version", "key"], name="hazard_key_per_version"),
            models.UniqueConstraint(fields=["version", "position"], name="hazard_position_per_version"),
            models.CheckConstraint(condition=Q(severity__gte=0), name="hazard_nonnegative_severity"),
        ]


class MethodVersion(models.Model):
    code = models.SlugField(primary_key=True)


class Assessment(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="assessments")
    title = models.CharField("titolo", max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    current_revision = models.ForeignKey(
        "Revision", on_delete=models.PROTECT, null=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at", "-pk"]
        permissions = [
            ("view_own_assessment", "Consulta le valutazioni pubblicate della propria azienda"),
            ("publish_assessment", "Pubblica le valutazioni"),
            ("revise_assessment", "Apri correzioni alle valutazioni pubblicate"),
        ]


class Revision(models.Model):
    assessment = models.ForeignKey(Assessment, on_delete=models.PROTECT, related_name="revisions")
    number = models.PositiveIntegerField()
    catalog_version = models.ForeignKey(CatalogVersion, on_delete=models.PROTECT)
    method = models.ForeignKey(MethodVersion, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    edit_version = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["assessment", "number"], name="revision_number_per_assessment"),
            models.UniqueConstraint(
                fields=["assessment"], condition=Q(published_at__isnull=True), name="one_draft_per_assessment"
            ),
        ]


class Probability(models.Model):
    revision = models.ForeignKey(Revision, on_delete=models.PROTECT, related_name="probabilities")
    row = models.ForeignKey(CatalogRow, on_delete=models.PROTECT)
    hazard = models.ForeignKey(Hazard, on_delete=models.PROTECT)
    value = models.DecimalField(max_digits=28, decimal_places=12)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["revision", "row", "hazard"], name="one_probability_per_cell"),
            models.CheckConstraint(condition=Q(value__gte=0), name="nonnegative_probability"),
        ]
