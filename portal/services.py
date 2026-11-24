from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .calculation import CURRENT_METHOD
from .models import Assessment, Catalog, CatalogCategory, CatalogRow, CatalogVersion, Company, Hazard, Probability, Revision


class Conflict(Exception):
    """Another request changed the editable version."""


class CatalogError(Exception):
    pass


def removable_company_accounts(company):
    return company.user_set.filter(is_staff=False, is_superuser=False)


@transaction.atomic
def delete_company(company_id, *, delete_accounts):
    company = Company.objects.select_for_update().get(pk=company_id)
    assessments = company.assessments.order_by("pk")
    # Revision edits acquire the assessment lock before touching its data.
    list(assessments.select_for_update().values_list("pk", flat=True))

    revisions = Revision.objects.filter(assessment__company=company)
    Probability.objects.filter(revision__in=revisions).delete()
    assessments.update(current_revision=None)
    revisions.delete()
    assessments.delete()

    if delete_accounts:
        removable_company_accounts(company).delete()
    company.user_set.update(company=None)
    company.delete()


@transaction.atomic
def new_assessment(company, title):
    catalog = Catalog.objects.get(pk=1)
    if not catalog.current_id:
        raise CatalogError("Il catalogo iniziale deve essere importato prima di creare una valutazione.")
    assessment = Assessment.objects.create(company=company, title=title)
    revision = Revision.objects.create(
        assessment=assessment, number=1, catalog_version_id=catalog.current_id, method_id=CURRENT_METHOD
    )
    return assessment, revision


@transaction.atomic
def start_revision(assessment_id, source_id):
    assessment = Assessment.objects.select_for_update().get(pk=assessment_id)
    if not assessment.current_revision_id or assessment.current_revision_id != source_id:
        raise Conflict
    draft = assessment.revisions.filter(published_at__isnull=True).first()
    if draft:
        return draft
    source = assessment.current_revision
    draft = Revision.objects.create(
        assessment=assessment, number=source.number + 1, catalog_version=source.catalog_version, method=source.method
    )
    Probability.objects.bulk_create([
        Probability(revision=draft, row_id=row, hazard_id=hazard, value=value)
        for row, hazard, value in source.probabilities.values_list("row_id", "hazard_id", "value")
    ], batch_size=1000)
    return draft


def _locked_draft(assessment_id, revision_id, expected):
    assessment = Assessment.objects.select_for_update().filter(pk=assessment_id).first()
    if assessment is None:
        raise Conflict
    draft = assessment.revisions.filter(pk=revision_id, published_at__isnull=True).first()
    if draft is None or draft.edit_version != expected:
        raise Conflict
    return assessment, draft


def _bump_version(draft):
    draft.edit_version += 1
    draft.save(update_fields=["edit_version"])


@transaction.atomic
def save_probabilities(assessment_id, revision_id, expected, row_id, values):
    _, draft = _locked_draft(assessment_id, revision_id, expected)
    row = CatalogRow.objects.get(pk=row_id, category__version_id=draft.catalog_version_id)
    hazard_ids = set(draft.catalog_version.hazards.values_list("pk", flat=True))
    if set(values) != hazard_ids:
        raise ValueError("Le probabilità devono fare riferimento ai pericoli della revisione.")
    saved = draft.probabilities.filter(row=row)
    updates = {hazard: value for hazard, value in values.items() if value is not None}
    if dict(saved.values_list("hazard_id", "value")) == updates:
        return False
    saved.delete()
    Probability.objects.bulk_create([
        Probability(revision=draft, row=row, hazard_id=hazard, value=value)
        for hazard, value in updates.items()
    ])
    _bump_version(draft)
    return True


@transaction.atomic
def change_probabilities_in_bulk(assessment_id, revision_id, expected, selected_row, scope, action):
    if scope not in {"row", "all"} or action not in {"clear", "zero"}:
        raise ValueError("Comando non valido.")
    _, draft = _locked_draft(assessment_id, revision_id, expected)
    rows = CatalogRow.objects.filter(category__version_id=draft.catalog_version_id)
    if scope == "row":
        rows = rows.filter(pk=selected_row)
    row_ids = list(rows.values_list("pk", flat=True))
    saved = draft.probabilities.filter(row_id__in=row_ids)
    if action == "clear":
        deleted, _ = saved.delete()
        if not deleted:
            return False
    else:
        filled = set(saved.values_list("row_id", "hazard_id"))
        hazards = list(draft.catalog_version.hazards.values_list("pk", flat=True))
        blanks = [
            Probability(revision=draft, row_id=row, hazard_id=hazard, value=Decimal(0))
            for row in row_ids for hazard in hazards
            if (row, hazard) not in filled
        ]
        if not blanks:
            return False
        Probability.objects.bulk_create(blanks, batch_size=1000)
    _bump_version(draft)
    return True


@transaction.atomic
def publish_revision(assessment_id, revision_id, expected):
    assessment, draft = _locked_draft(assessment_id, revision_id, expected)
    draft.published_at = timezone.now()
    draft.save(update_fields=["published_at"])
    assessment.current_revision = draft
    assessment.save(update_fields=["current_revision"])


@transaction.atomic
def discard_revision(assessment_id, revision_id, expected):
    assessment, draft = _locked_draft(assessment_id, revision_id, expected)
    draft.probabilities.all().delete()
    draft.delete()
    if assessment.current_revision_id is None:
        assessment.delete()
    return assessment.current_revision_id


@transaction.atomic
def start_catalog_draft():
    catalog = Catalog.objects.select_for_update().get(pk=1)
    if catalog.draft_id:
        return catalog.draft
    current = catalog.current
    if not current:
        raise CatalogError("Il catalogo iniziale deve essere importato.")
    draft = CatalogVersion.objects.create(number=current.number + 1)
    categories = current.categories.all()
    copies = CatalogCategory.objects.bulk_create([
        CatalogCategory(version=draft, key=category.key, name=category.name) for category in categories
    ])
    by_source = {category.pk: copy for category, copy in zip(categories, copies)}
    CatalogRow.objects.bulk_create([
        CatalogRow(category=by_source[row.category_id], key=row.key, label=row.label,
                   intended_use=row.intended_use, position=row.position)
        for row in CatalogRow.objects.filter(category__version=current)
    ])
    Hazard.objects.bulk_create([
        Hazard(version=draft, key=hazard.key, name=hazard.name, kind=hazard.kind,
               severity=hazard.severity, position=hazard.position)
        for hazard in current.hazards.all()
    ])
    catalog.draft = draft
    catalog.save(update_fields=["draft"])
    return draft


def _locked_catalog_draft(draft_id, expected):
    catalog = Catalog.objects.select_for_update().get(pk=1)
    if catalog.draft_id != draft_id:
        raise Conflict
    draft = catalog.draft
    if draft.edit_version != expected or draft.published_at:
        raise Conflict
    return catalog, draft


def _next_catalog_position(draft):
    maximum = CatalogRow.objects.filter(category__version=draft).aggregate(Max("position"))["position__max"]
    return 1 if maximum is None else maximum + 1


@transaction.atomic
def save_category(draft_id, expected, category_id, name):
    _, draft = _locked_catalog_draft(draft_id, expected)
    if draft.categories.exclude(pk=category_id).filter(name__iexact=name).exists():
        raise CatalogError("Esiste già una categoria con questo nome.")
    if category_id is None:
        category = draft.categories.create(name=name)
        category.rows.create(label="", position=_next_catalog_position(draft))
    else:
        category = draft.categories.get(pk=category_id)
        category.name = name
        category.save(update_fields=["name"])
    _bump_version(draft)


@transaction.atomic
def save_catalog_row(draft_id, expected, row_id, category_id, label):
    _, draft = _locked_catalog_draft(draft_id, expected)
    category = draft.categories.get(pk=category_id)
    if category.rows.exclude(pk=row_id).filter(label__iexact=label).exists():
        raise CatalogError("Esiste già una voce con questo nome nella categoria.")
    if row_id is None:
        category.rows.create(label=label, position=_next_catalog_position(draft))
    else:
        row = CatalogRow.objects.get(pk=row_id, category__version=draft)
        row.category = category
        row.label = label
        row.save(update_fields=["category", "label"])
    _bump_version(draft)


@transaction.atomic
def save_catalog_hazard(draft_id, expected, severity, *, hazard_id=None, name=None, kind=None):
    _, draft = _locked_catalog_draft(draft_id, expected)
    if hazard_id is None:
        if draft.hazards.filter(name__iexact=name, kind=kind).exists():
            raise CatalogError("Esiste già un pericolo con questo nome e tipo.")
        maximum = draft.hazards.aggregate(Max("position"))["position__max"] or 0
        draft.hazards.create(name=name, kind=kind, severity=severity, position=maximum + 1)
    else:
        hazard = draft.hazards.get(pk=hazard_id)
        hazard.severity = severity
        hazard.save(update_fields=["severity"])
    _bump_version(draft)


@transaction.atomic
def publish_catalog(draft_id, expected):
    catalog, draft = _locked_catalog_draft(draft_id, expected)
    draft.published_at = timezone.now()
    draft.save(update_fields=["published_at"])
    catalog.current = draft
    catalog.draft = None
    catalog.save(update_fields=["current", "draft"])


@transaction.atomic
def discard_catalog(draft_id, expected):
    catalog, draft = _locked_catalog_draft(draft_id, expected)
    catalog.draft = None
    catalog.save(update_fields=["draft"])
    CatalogRow.objects.filter(category__version=draft).delete()
    draft.categories.all().delete()
    draft.hazards.all().delete()
    draft.delete()
