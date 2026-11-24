from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.db import IntegrityError, connections
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect

from . import services
from .forms import CompanyForm
from .models import Company, Probability, Revision, User


class PortalAdminSite(admin.AdminSite):
    site_header = "Amministrazione del portale"

    def has_permission(self, request):
        return super().has_permission(request) and request.user.is_superuser


class AccountCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("email",)


class AccountChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User


administration = PortalAdminSite()


@admin.register(Company, site=administration)
class CompanyAdmin(admin.ModelAdmin):
    form = CompanyForm
    list_display = ("name",)
    search_fields = ("name",)
    actions = None

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        companies = super().get_queryset(request)
        if request.method == "POST" and connections[companies.db].in_atomic_block:
            return companies.select_for_update()
        return companies

    def change_view(self, request, object_id, form_url="", extra_context=None):
        context = {**(extra_context or {}), "show_save_and_continue": False}
        return super().change_view(request, object_id, form_url, extra_context=context)

    def delete_view(self, request, object_id, extra_context=None):
        if request.method == "POST" and request.POST.get("post") != "yes":
            return HttpResponseBadRequest("Conferma l’eliminazione dalla pagina dell’azienda.")
        try:
            return super().delete_view(request, object_id, extra_context)
        except IntegrityError:
            self.message_user(request, "Impossibile eliminare l’azienda. I dati sono stati conservati.", messages.ERROR)
            return redirect("admin:portal_company_change", object_id)

    def get_deleted_objects(self, objs, request):
        # The service removes company data in the order required by the protected relations.
        return [], {}, set(), []

    def render_delete_form(self, request, context):
        company = context["object"]
        revisions = Revision.objects.filter(assessment__company=company)
        context.update(
            model_count=[
                ("Valutazioni", company.assessments.count()),
                ("Revisioni e bozze", revisions.count()),
                ("Probabilità inserite", Probability.objects.filter(revision__in=revisions).count()),
            ],
            linked_accounts=company.user_set.count(),
            removable_accounts=services.removable_company_accounts(company).count(),
        )
        return super().render_delete_form(request, context)

    def delete_model(self, request, obj):
        services.delete_company(obj.pk, delete_accounts=request.POST.get("delete_accounts") == "yes")


@admin.register(User, site=administration)
class AccountAdmin(UserAdmin):
    form = AccountChangeForm
    add_form = AccountCreationForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dati personali", {"fields": ("first_name", "last_name")}),
        ("Accesso", {"fields": ("is_active", "company", "groups", "is_staff", "is_superuser")}),
        ("Date", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"fields": ("email", "company", "groups", "password1", "password2")}),)
    ordering = ("email",)
    list_display = ("email", "company", "is_active", "is_superuser")
    list_filter = ("is_active", "groups", "is_superuser")
    search_fields = ("email", "first_name", "last_name", "company__name")
    filter_horizontal = ("groups",)

    def has_delete_permission(self, request, obj=None):
        return False
