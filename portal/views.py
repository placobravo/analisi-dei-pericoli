from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.db.models.functions import Lower
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from . import services
from .calculation import format_number
from .forms import (
    AssessmentForm, BulkForm, CatalogRowForm, CategoryForm, CompanyForm,
    EditVersionForm, HazardSeverityForm, NewHazardForm, ProbabilityForm,
)
from .matrix import matrix_rows
from .models import Assessment, Catalog, CatalogRow, CatalogVersion, Company, Hazard, Revision


def private(permission=None):
    def decorate(view):
        if permission:
            view = permission_required(f"portal.{permission}", raise_exception=True)(view)
        return never_cache(login_required(view))
    return decorate


def _form_page(request, title, form, return_url, *, description="", submit_label="Salva"):
    return render(request, "portal/form.html", {
        "title": title, "form": form, "return_url": return_url,
        "description": description, "submit_label": submit_label,
    })


def _conflict(request, return_url):
    return render(request, "portal/conflict.html", {"return_url": return_url}, status=409)


def _revision_url(pk, rid, row=None):
    path = reverse("revision", args=[pk, rid])
    return f"{path}?{urlencode({'voce': row.pk})}#compilazione" if row else path


@private()
@require_safe
def home(request):
    user = request.user
    if user.has_perm("portal.view_assessment"):
        return render(request, "portal/companies.html", {"companies": Company.objects.all()})
    if user.has_perm("portal.view_own_assessment") and user.company_id:
        return _company_page(request, user.company, operator=False)
    raise PermissionDenied


@private("add_company")
@require_http_methods(["GET", "HEAD", "POST"])
def company_create(request):
    form = CompanyForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        company = form.save()
        return redirect("company", pk=company.pk)
    return _form_page(request, "Nuova azienda", form, reverse("home"))


def _company_page(request, company, operator):
    assessments = company.assessments.select_related("current_revision")
    if not operator:
        assessments = assessments.filter(current_revision__published_at__isnull=False)
    return render(request, "portal/company.html", {
        "company": company, "assessments": assessments, "operator": operator,
    })


@private("view_assessment")
@require_safe
def company_detail(request, pk):
    return _company_page(request, get_object_or_404(Company, pk=pk), operator=True)


@private("add_assessment")
@require_http_methods(["GET", "HEAD", "POST"])
def assessment_create(request, pk):
    company = get_object_or_404(Company, pk=pk)
    form = AssessmentForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        try:
            assessment, revision = services.new_assessment(company, form.cleaned_data["title"])
        except services.CatalogError as error:
            form.add_error(None, str(error))
        else:
            return redirect("revision", pk=assessment.pk, rid=revision.pk)
    return _form_page(request, f"Nuova valutazione · {company.name}", form, reverse("company", args=[pk]))


@private()
@require_safe
def assessment_detail(request, pk):
    user = request.user
    assessments = Assessment.objects.select_related("company", "current_revision")
    if user.has_perm("portal.view_assessment"):
        assessment = get_object_or_404(assessments, pk=pk)
        revision = assessment.revisions.filter(published_at__isnull=True).first() or assessment.current_revision
        if revision is None:
            raise Http404
        return _revision_page(request, assessment, revision, operator=True)
    if user.has_perm("portal.view_own_assessment") and user.company_id:
        assessment = get_object_or_404(
            assessments, pk=pk, company_id=user.company_id, current_revision__published_at__isnull=False
        )
        return _revision_page(request, assessment, assessment.current_revision, operator=False)
    raise PermissionDenied


def _get_revision(pk, rid):
    return get_object_or_404(Revision.objects.select_related("assessment__company"), assessment_id=pk, pk=rid)


def _catalog_rows(version_id):
    return (
        CatalogRow.objects.filter(category__version_id=version_id)
        .select_related("category")
        .order_by(Lower("category__name"), Lower("label"), "pk")
    )


def _catalog_hazards(version_id):
    return Hazard.objects.filter(version_id=version_id).order_by("kind", Lower("name"), "pk")


def _saved_probabilities(revision, row):
    return {
        hazard_id: format_number(value)
        for hazard_id, value in revision.probabilities.filter(row=row).values_list("hazard_id", "value")
    }


@private("view_assessment")
@require_safe
def revision_detail(request, pk, rid):
    revision = _get_revision(pk, rid)
    return _revision_page(request, revision.assessment, revision, operator=True)


def _revision_page(request, assessment, revision, *, operator, selected=None, form=None):
    rows = list(_catalog_rows(revision.catalog_version_id))
    hazards = list(_catalog_hazards(revision.catalog_version_id))
    is_draft = revision.published_at is None
    editable = operator and is_draft and request.user.has_perm("portal.change_revision")
    if editable and selected is None and rows:
        selected_id = request.GET.get("voce")
        selected = next((row for row in rows if str(row.pk) == selected_id), rows[0])
    matrix, columns = matrix_rows(rows, hazards, revision)
    probability_fields = []
    if selected is not None and editable:
        if form is None:
            form = ProbabilityForm(
                hazards, _saved_probabilities(revision, selected), initial={"version": revision.edit_version},
            )
        probability_fields = [(hazard, format_number(hazard.severity), form[form.for_hazard[hazard.pk]]) for hazard in hazards]
    return render(request, "portal/assessment.html", {
        "assessment": assessment, "revision": revision, "operator": operator, "rows": rows,
        "history": assessment.revisions.all() if operator else (),
        "is_draft": is_draft, "editable": editable, "selected": selected, "form": form,
        "probability_fields": probability_fields, "columns": columns, "matrix": matrix,
        "hazard_kinds": Hazard.Kind.choices,
    }, status=400 if form is not None and form.errors else 200)


@private("change_revision")
@require_POST
def probability_save(request, pk, rid, row_id):
    revision = _get_revision(pk, rid)
    row = get_object_or_404(_catalog_rows(revision.catalog_version_id), pk=row_id)
    form = ProbabilityForm(
        _catalog_hazards(revision.catalog_version_id), _saved_probabilities(revision, row), request.POST,
    )
    if not form.is_valid():
        return _revision_page(request, revision.assessment, revision, operator=True, selected=row, form=form)
    try:
        changed = services.save_probabilities(pk, rid, form.cleaned_data["version"], row.pk, form.probabilities())
    except services.Conflict:
        return _conflict(request, _revision_url(pk, rid, row))
    if changed:
        messages.success(request, "Probabilità salvate.")
    return redirect(_revision_url(pk, rid, row))


@private("change_revision")
@require_POST
def probability_bulk(request, pk, rid, row_id):
    revision = _get_revision(pk, rid)
    row = get_object_or_404(_catalog_rows(revision.catalog_version_id), pk=row_id)
    return_url = _revision_url(pk, rid, row)
    form = BulkForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Comando non valido.")
    data = form.cleaned_data
    if revision.published_at or revision.edit_version != data["version"]:
        return _conflict(request, return_url)
    if request.POST.get("conferma") != "1":
        return render(request, "portal/bulk.html", {
            "revision": revision, "row": row, "form_data": data, "return_url": return_url,
        })
    try:
        changed = services.change_probabilities_in_bulk(pk, rid, data["version"], row.pk, data["scope"], data["action"])
    except services.Conflict:
        return _conflict(request, return_url)
    if changed:
        messages.success(request, "Probabilità aggiornate.")
    else:
        messages.info(request, "Nessuna probabilità da aggiornare.")
    return redirect(return_url)


@private("publish_assessment")
@require_POST
def revision_publish(request, pk, rid):
    _get_revision(pk, rid)
    form = EditVersionForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Versione della bozza non valida.")
    try:
        services.publish_revision(pk, rid, form.cleaned_data["version"])
    except services.Conflict:
        return _conflict(request, _revision_url(pk, rid))
    messages.success(request, "Revisione pubblicata.")
    return redirect("revision", pk=pk, rid=rid)


@private("change_revision")
@require_http_methods(["GET", "HEAD", "POST"])
def revision_discard(request, pk, rid):
    revision = _get_revision(pk, rid)
    return_url = _revision_url(pk, rid)
    if revision.published_at is not None:
        return _conflict(request, return_url)
    form = EditVersionForm(
        request.POST if request.method == "POST" else None, initial={"version": revision.edit_version},
    )
    if form.is_valid():
        try:
            current_id = services.discard_revision(pk, rid, form.cleaned_data["version"])
        except services.Conflict:
            return _conflict(request, return_url)
        messages.success(request, "Bozza della valutazione annullata.")
        if current_id is None:
            return redirect("company", pk=revision.assessment.company_id)
        return redirect("revision", pk=pk, rid=current_id)

    if revision.assessment.current_revision_id is None:
        description = "Annullando la bozza elimini la valutazione e le probabilità inserite."
    else:
        description = "Annullando la bozza elimini le modifiche e torni alla revisione pubblicata."
    return _form_page(
        request, "Annulla bozza della valutazione", form, return_url,
        description=description, submit_label="Conferma annullamento",
    )


@private("revise_assessment")
@require_POST
def revision_create(request, pk, rid):
    _get_revision(pk, rid)
    try:
        draft = services.start_revision(pk, rid)
    except services.Conflict:
        return _conflict(request, reverse("assessment", args=[pk]))
    return redirect("revision", pk=pk, rid=draft.pk)


@private("change_catalogversion")
@require_safe
def catalog_detail(request):
    catalog = Catalog.objects.select_related("current", "draft").get(pk=1)
    versions = list(
        CatalogVersion.objects.filter(published_at__isnull=False).exclude(pk=catalog.draft_id).order_by("-number")
    )
    if catalog.draft:
        versions.insert(0, catalog.draft)
    version = catalog.draft or catalog.current
    if "versione" in request.GET:
        version = next((item for item in versions if str(item.number) == request.GET["versione"]), None)
        if version is None:
            raise Http404
    categories = ()
    if version:
        categories = version.categories.order_by(Lower("name"), "pk").prefetch_related(
            Prefetch("rows", queryset=CatalogRow.objects.order_by(Lower("label"), "pk"), to_attr="catalog_rows")
        )
    return render(request, "portal/catalog.html", {
        "catalog": catalog, "version": version, "versions": versions, "categories": categories,
        "editing_draft": version is not None and version.pk == catalog.draft_id,
        "hazards": _catalog_hazards(version.pk) if version else (),
    })


@private("change_catalogversion")
@require_POST
def catalog_start(request):
    try:
        services.start_catalog_draft()
    except services.CatalogError as error:
        messages.error(request, str(error))
    return redirect("catalog")


@private("change_catalogversion")
@require_POST
def catalog_publish(request, vid):
    form = EditVersionForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Versione della bozza non valida.")
    try:
        services.publish_catalog(vid, form.cleaned_data["version"])
    except services.Conflict:
        return _conflict(request, reverse("catalog"))
    messages.success(request, "Nuova versione del catalogo pubblicata.")
    return redirect("catalog")


def _catalog_draft(vid):
    catalog = Catalog.objects.select_related("draft").get(pk=1)
    if catalog.draft_id != vid:
        raise services.Conflict
    return catalog.draft


@private("change_catalogversion")
@require_http_methods(["GET", "HEAD", "POST"])
def catalog_discard(request, vid):
    return_url = reverse("catalog")
    try:
        draft = _catalog_draft(vid)
        form = EditVersionForm(
            request.POST if request.method == "POST" else None, initial={"version": draft.edit_version}
        )
        if form.is_valid():
            services.discard_catalog(vid, form.cleaned_data["version"])
            messages.success(request, "Bozza di catalogo annullata.")
            return redirect(return_url)
    except services.Conflict:
        return _conflict(request, return_url)
    return _form_page(
        request, "Annulla bozza di catalogo", form, return_url,
        description=f"Le modifiche della bozza v{draft.number} saranno eliminate.",
        submit_label="Conferma annullamento",
    )


@private("change_catalogversion")
@require_http_methods(["GET", "HEAD", "POST"])
def catalog_category(request, vid, cid=None):
    return_url = reverse("catalog")
    try:
        draft = _catalog_draft(vid)
    except services.Conflict:
        return _conflict(request, return_url)
    category = get_object_or_404(draft.categories, pk=cid) if cid else None
    form = CategoryForm(request.POST if request.method == "POST" else None, initial={
        "version": draft.edit_version, "name": category.name if category else "",
    })
    if form.is_valid():
        try:
            services.save_category(vid, form.cleaned_data["version"], cid, form.cleaned_data["name"])
        except services.Conflict:
            return _conflict(request, return_url)
        except services.CatalogError as error:
            form.add_error("name", str(error))
        else:
            return redirect("catalog")
    return _form_page(request, "Modifica categoria" if category else "Nuova categoria", form, return_url)


@private("change_catalogversion")
@require_http_methods(["GET", "HEAD", "POST"])
def catalog_row(request, vid, row_id=None):
    return_url = reverse("catalog")
    try:
        draft = _catalog_draft(vid)
    except services.Conflict:
        return _conflict(request, return_url)
    row = get_object_or_404(CatalogRow.objects.filter(category__version=draft).exclude(label=""), pk=row_id) if row_id else None
    form = CatalogRowForm(draft, request.POST if request.method == "POST" else None, initial={
        "version": draft.edit_version, "category": row.category_id if row else None, "label": row.label if row else "",
    })
    if form.is_valid():
        try:
            data = form.cleaned_data
            services.save_catalog_row(vid, data["version"], row_id, data["category"].pk, data["label"])
        except services.Conflict:
            return _conflict(request, return_url)
        except services.CatalogError as error:
            form.add_error(None, str(error))
        else:
            return redirect("catalog")
    title = "Modifica sottocategoria" if row else "Nuova sottocategoria"
    return _form_page(request, title, form, return_url)


@private("change_catalogversion")
@require_http_methods(["GET", "HEAD", "POST"])
def catalog_hazard(request, vid, hid=None):
    return_url = reverse("catalog") + "#pericoli"
    try:
        draft = _catalog_draft(vid)
    except services.Conflict:
        return _conflict(request, return_url)
    hazard = get_object_or_404(draft.hazards, pk=hid) if hid else None
    form_class = HazardSeverityForm if hazard else NewHazardForm
    form = form_class(request.POST if request.method == "POST" else None, initial={
        "version": draft.edit_version,
        "severity": format_number(hazard.severity) if hazard else "",
    })
    if form.is_valid():
        data = form.cleaned_data
        try:
            services.save_catalog_hazard(
                vid, data["version"], data["severity"], hazard_id=hid, name=data.get("name"), kind=data.get("kind")
            )
        except services.Conflict:
            return _conflict(request, return_url)
        except services.CatalogError as error:
            form.add_error("name", str(error))
        else:
            return redirect(return_url)
    title = f"Modifica gravità · {hazard.name}" if hazard else "Nuovo pericolo"
    return _form_page(request, title, form, return_url)
