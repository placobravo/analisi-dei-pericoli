from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.contrib.auth.models import Group
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from . import services
from .calculation import calculate_v1
from .models import Catalog, CatalogCategory, CatalogRow, CatalogVersion, Company, Hazard, MethodVersion, Probability, User


def initial_catalog():
    version = CatalogVersion.objects.create(number=1, published_at=timezone.now())
    Catalog.objects.update_or_create(pk=1, defaults={"current": version})
    MethodVersion.objects.get_or_create(code="gxp-v1")
    category = CatalogCategory.objects.create(version=version, name="Categoria campione")
    general = CatalogRow.objects.create(category=category, position=1)
    detail = CatalogRow.objects.create(category=category, label="Voce campione", position=2)
    hazard = Hazard.objects.create(version=version, name="Pericolo campione", kind="B", severity=2, position=1)
    return version, general, detail, hazard


class PortalWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.v1, cls.general, cls.detail, cls.hazard = initial_catalog()
        cls.company_a = Company.objects.create(name="Alfa")
        cls.company_b = Company.objects.create(name="Beta")
        cls.operator = User.objects.create_user(email="operatore@example.test")
        cls.operator.groups.add(Group.objects.get(name="Operatore"))
        cls.reader = User.objects.create_user(email="cliente@example.test", company=cls.company_a)
        cls.reader.groups.add(Group.objects.get(name="Cliente"))
        cls.assessment, cls.draft = services.new_assessment(cls.company_a, "Visita Alfa")
        cls.other, cls.other_draft = services.new_assessment(cls.company_b, "Visita Beta")

    def revision_url(self, view, revision=None, *args):
        return reverse(view, args=[self.assessment.pk, (revision or self.draft).pk, *args])

    def save(self, row, value, version, revision=None):
        return self.client.post(self.revision_url("probability_save", revision, row.pk), {
            "version": version, f"p_{self.hazard.pk}": value,
        })

    def test_client_isolation_current_revision_only_and_live_revocation(self):
        reader = Client()
        reader.force_login(self.reader)
        url = reverse("assessment", args=[self.assessment.pk])
        self.assertEqual(reader.get(url).status_code, 404)
        services.publish_revision(self.other.pk, self.other_draft.pk, 0)
        self.assertEqual(reader.get(reverse("assessment", args=[self.other.pk])).status_code, 404)
        self.assertNotContains(reader.get(reverse("home")), "Visita Beta")

        self.client.force_login(self.operator)
        self.assertEqual(self.save(self.general, "1,25", 0).status_code, 302)
        self.assertEqual(self.client.post(self.revision_url("revision_publish"), {"version": 1}).status_code, 302)
        self.assertContains(reader.get(url), ">2,5</span>")
        self.assertEqual(self.client.post(self.revision_url("revision_create")).status_code, 302)
        corrected = self.assessment.revisions.get(published_at__isnull=True)
        self.assertEqual(self.save(self.general, "5", 0, corrected).status_code, 302)
        self.assertContains(reader.get(url), ">2,5</span>")
        self.assertEqual(reader.get(self.revision_url("revision", corrected)).status_code, 403)
        self.assertEqual(reader.post(self.revision_url("revision_publish", corrected), {"version": 1}).status_code, 403)
        self.assertEqual(self.client.post(self.revision_url("revision_publish", corrected), {"version": 1}).status_code, 302)

        self.assertContains(reader.get(url), "aria-label=\"10, fascia Alta\"")
        self.assertEqual(reader.get(self.revision_url("revision")).status_code, 403)
        self.assertContains(self.client.get(self.revision_url("revision")), ">2,5</span>")
        User.objects.filter(pk=self.reader.pk).update(company=None)
        self.assertEqual(reader.get(url).status_code, 403)
        self.operator.groups.clear()
        self.assertEqual(self.client.get(self.revision_url("revision", corrected)).status_code, 403)

    def test_admin_renames_company_without_affecting_its_links(self):
        url = reverse("admin:portal_company_change", args=[self.company_a.pk])
        self.client.force_login(self.operator)
        self.assertEqual(self.client.post(url, {"name": "Alfa Nuova"}).status_code, 302)
        self.company_a.refresh_from_db()
        self.assertEqual(self.company_a.name, "Alfa")

        self.client.force_login(User.objects.create_superuser(email="admin@example.test"))
        self.assertContains(self.client.get(reverse("admin:portal_company_changelist")), "Alfa")
        change_form = self.client.get(url)
        self.assertContains(change_form, 'name="_save"')
        self.assertNotContains(change_form, 'name="_continue"')
        self.assertEqual(self.client.post(url, {"name": "Alfa Nuova"}).status_code, 302)
        self.assertContains(self.client.get(reverse("company", args=[self.company_a.pk])), "Alfa Nuova")
        self.reader.refresh_from_db()
        self.assessment.refresh_from_db()
        self.assertEqual(self.reader.company_id, self.company_a.pk)
        self.assertEqual(self.assessment.company_id, self.company_a.pk)

    def test_admin_company_delete_requires_confirmation_and_detaches_accounts_by_default(self):
        self.client.force_login(User.objects.create_superuser(email="admin@example.test"))
        url = reverse("admin:portal_company_delete", args=[self.company_a.pk])
        confirmation = self.client.get(url)
        self.assertContains(confirmation, 'name="post"')
        self.assertContains(confirmation, 'name="delete_accounts"')
        self.assertEqual(self.client.post(url, {"delete_accounts": "yes"}).status_code, 400)
        self.assertTrue(Company.objects.filter(pk=self.company_a.pk).exists())
        self.assertRedirects(self.client.post(url, {"post": "yes"}), reverse("admin:portal_company_changelist"))
        self.assertFalse(Company.objects.filter(pk=self.company_a.pk).exists())
        self.reader.refresh_from_db()
        self.assertIsNone(self.reader.company_id)

    def test_admin_can_delete_company_history_and_ordinary_accounts(self):
        services.save_probabilities(self.assessment.pk, self.draft.pk, 0, self.general.pk, {self.hazard.pk: Decimal(2)})
        services.publish_revision(self.assessment.pk, self.draft.pk, 1)
        published = services.start_revision(self.assessment.pk, self.draft.pk)
        services.publish_revision(self.assessment.pk, published.pk, 0)
        pending = services.start_revision(self.assessment.pk, published.pk)
        services.save_probabilities(self.other.pk, self.other_draft.pk, 0, self.general.pk, {self.hazard.pk: Decimal(3)})
        revisions = [self.draft.pk, published.pk, pending.pk]

        administrator = User.objects.create_superuser(email="admin@example.test", company=self.company_a)
        self.client.force_login(administrator)
        url = reverse("admin:portal_company_delete", args=[self.company_a.pk])
        confirmation = self.client.get(url)
        self.assertEqual(dict(confirmation.context["model_count"]), {
            "Valutazioni": 1, "Revisioni e bozze": 3, "Probabilità inserite": 3,
        })
        self.assertEqual(confirmation.context["removable_accounts"], 1)
        self.assertRedirects(
            self.client.post(url, {"post": "yes", "delete_accounts": "yes"}),
            reverse("admin:portal_company_changelist"),
        )

        self.assertFalse(Company.objects.filter(pk=self.company_a.pk).exists())
        self.assertFalse(self.company_a.assessments.filter(pk=self.assessment.pk).exists())
        self.assertFalse(self.assessment.revisions.filter(pk__in=revisions).exists())
        self.assertFalse(Probability.objects.filter(revision_id__in=revisions).exists())
        self.assertFalse(User.objects.filter(pk=self.reader.pk).exists())
        administrator.refresh_from_db()
        self.assertIsNone(administrator.company_id)
        self.assertEqual(Company.objects.get(pk=self.company_b.pk).assessments.get().pk, self.other.pk)
        self.assertEqual(self.other_draft.probabilities.get().value, Decimal(3))
        self.assertEqual(Catalog.objects.get(pk=1).current_id, self.v1.pk)

    def test_admin_company_delete_rolls_back_if_a_related_record_is_protected(self):
        self.other.current_revision = self.draft
        self.other.save(update_fields=["current_revision"])
        services.save_probabilities(self.assessment.pk, self.draft.pk, 0, self.general.pk, {self.hazard.pk: Decimal(2)})
        self.client.force_login(User.objects.create_superuser(email="admin@example.test"))
        url = reverse("admin:portal_company_delete", args=[self.company_a.pk])
        self.assertRedirects(
            self.client.post(url, {"post": "yes", "delete_accounts": "yes"}),
            reverse("admin:portal_company_change", args=[self.company_a.pk]),
        )
        self.assertEqual(self.draft.probabilities.get().value, Decimal(2))
        self.reader.refresh_from_db()
        self.assertEqual(self.reader.company_id, self.company_a.pk)

    def test_independent_rows_stale_writes_and_confirmed_bulk(self):
        self.client.force_login(self.operator)
        self.assertContains(self.client.get(self.revision_url("revision") + f"?voce={self.general.pk}"), "Salva probabilità")
        self.assertEqual(self.save(self.general, "0", 0).status_code, 302)
        self.assertEqual(self.save(self.detail, "2,5", 0).status_code, 409)
        self.assertEqual(self.client.post(self.revision_url("revision_publish"), {"version": 0}).status_code, 409)
        self.assertEqual(self.save(self.detail, "2,5", 1).status_code, 302)
        self.assertEqual(self.save(self.detail, "-1", 2).status_code, 400)
        self.assertEqual(Probability.objects.get(revision=self.draft, row=self.general).value, 0)
        self.assertEqual(Probability.objects.get(revision=self.draft, row=self.detail).value, Decimal("2.5"))
        bulk = self.revision_url("probability_bulk", self.draft, self.general.pk)
        data = {"version": 2, "scope": "row", "action": "clear"}
        self.assertContains(self.client.post(bulk, data), "Conferma")
        self.assertTrue(self.draft.probabilities.filter(row=self.general).exists())
        self.assertEqual(self.client.post(bulk, {**data, "conferma": 1}).status_code, 302)
        self.assertFalse(self.draft.probabilities.filter(row=self.general).exists())
        self.assertEqual(self.draft.probabilities.get(row=self.detail).value, Decimal("2.5"))
        original = self.draft.probabilities.get(row=self.detail)
        data = {"version": 3, "scope": "all", "action": "zero"}
        self.assertContains(self.client.post(bulk, data), "dell’intera bozza")
        self.assertEqual(self.client.post(bulk, {**data, "conferma": 1}).status_code, 302)
        self.assertEqual(self.draft.probabilities.get(row=self.general).value, 0)
        original.refresh_from_db()
        self.assertEqual(original.value, Decimal("2.5"))
        self.assertEqual(self.client.post(bulk, {**data, "version": 4, "conferma": 1}).status_code, 302)
        self.assertEqual(self.client.post(self.revision_url("revision_publish"), {"version": 4}).status_code, 302)
        self.assertEqual(self.save(self.general, "3", 4).status_code, 409)

    def test_zero_fills_blank_fields_only_in_the_selected_row(self):
        second_hazard = self.v1.hazards.create(name="Pericolo fisico", kind="F", severity=1, position=2)
        self.client.force_login(self.operator)
        self.assertEqual(self.save(self.general, "1,75", 0).status_code, 302)
        bulk = self.revision_url("probability_bulk", self.draft, self.general.pk)
        self.assertEqual(self.client.post(bulk, {
            "version": 1, "scope": "row", "action": "zero", "conferma": 1,
        }).status_code, 302)
        self.assertEqual(
            dict(self.draft.probabilities.filter(row=self.general).values_list("hazard_id", "value")),
            {self.hazard.pk: Decimal("1.75"), second_hazard.pk: Decimal(0)},
        )
        self.assertFalse(self.draft.probabilities.filter(row=self.detail).exists())

    def test_discarding_initial_draft_removes_unpublished_assessment(self):
        self.client.force_login(self.operator)
        url = self.revision_url("revision_discard")
        self.assertContains(self.client.get(self.revision_url("revision")), f'href="{url}"')
        self.assertContains(self.client.get(url), "Conferma annullamento")
        self.assertTrue(self.company_a.assessments.filter(pk=self.assessment.pk).exists())
        self.assertEqual(self.save(self.general, "2", 0).status_code, 302)
        self.assertEqual(self.client.post(url, {"version": 0}).status_code, 409)
        self.assertRedirects(self.client.post(url, {"version": 1}), reverse("company", args=[self.company_a.pk]))
        self.assertFalse(self.company_a.assessments.filter(pk=self.assessment.pk).exists())
        self.assertFalse(Probability.objects.filter(revision=self.draft).exists())

    def test_discarding_a_correction_keeps_the_published_revision(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.save(self.general, "2", 0).status_code, 302)
        services.publish_revision(self.assessment.pk, self.draft.pk, 1)
        correction = services.start_revision(self.assessment.pk, self.draft.pk)
        self.assertEqual(self.save(self.general, "4", 0, correction).status_code, 302)
        url = self.revision_url("revision_discard", correction)
        self.assertRedirects(self.client.post(url, {"version": 1}), self.revision_url("revision"))
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.current_revision, self.draft)
        self.assertFalse(self.assessment.revisions.filter(pk=correction.pk).exists())
        self.assertEqual(self.draft.probabilities.get().value, 2)
        self.assertEqual(self.client.post(self.revision_url("revision_discard"), {"version": 1}).status_code, 409)

    def test_catalog_edits_only_affect_new_assessments(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.post(reverse("catalog_start")).status_code, 302)
        draft = Catalog.objects.get(pk=1).draft
        category = draft.categories.get(key=self.general.category.key)
        rename = reverse("catalog_category", args=[draft.pk, category.pk])
        self.assertContains(self.client.get(reverse("catalog")), f'href="{rename}"')
        self.assertEqual(self.client.post(rename, {"version": 0, "name": "Categoria aggiornata"}).status_code, 302)
        self.assertEqual(self.client.post(rename, {"version": 0, "name": "Nome superato"}).status_code, 409)
        self.assertEqual(self.client.post(reverse("catalog_publish", args=[draft.pk]), {"version": 1}).status_code, 302)
        self.assertContains(self.client.get(self.revision_url("revision")), "Categoria campione")
        self.assertNotContains(self.client.get(self.revision_url("revision")), "Categoria aggiornata")
        _, revision = services.new_assessment(self.company_a, "Valutazione successiva")
        copied = CatalogRow.objects.get(category__version=revision.catalog_version, key=self.general.key)
        self.assertEqual(copied.category.name, "Categoria aggiornata")
        self.assertEqual(revision.catalog_version.hazards.get(key=self.hazard.key).severity, self.hazard.severity)

    def test_catalog_and_assessment_group_rows_by_category_and_sort_subcategories(self):
        self.client.force_login(self.operator)
        category = CatalogCategory.objects.create(version=self.v1, name="Altra categoria")
        last = category.rows.create(label="Voce Z", position=3)
        first = category.rows.create(label="voce A", position=4)
        general = category.rows.create(position=5)
        expected = [general, first, last, self.general, self.detail]
        page = self.client.get(reverse("catalog"))
        self.assertContains(page, "Categorie &amp; Sottocategorie")
        self.assertEqual([row for category in page.context["categories"] for row in category.catalog_rows], expected)
        self.assertEqual(self.client.get(self.revision_url("revision")).context["rows"], expected)

    def test_hazard_changes_only_apply_to_the_catalog_draft(self):
        self.client.force_login(self.operator)
        draft = services.start_catalog_draft()
        copied = draft.hazards.get(key=self.hazard.key)
        edit_url = reverse("catalog_hazard", args=[draft.pk, copied.pk])
        self.assertEqual(self.client.post(edit_url, {"version": 0, "severity": "3,5"}).status_code, 302)
        self.assertEqual(self.client.post(edit_url, {"version": 0, "severity": "4"}).status_code, 409)
        self.assertEqual(
            self.client.post(reverse("catalog_hazard_create", args=[draft.pk]), {
                "version": 1, "name": "Nuovo pericolo", "kind": "F", "severity": "1,25",
            }).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(reverse("catalog_hazard_create", args=[draft.pk]), {
                "version": 2, "name": "altro pericolo", "kind": "B", "severity": "2",
            }).status_code,
            302,
        )
        names = ["altro pericolo", self.hazard.name, "Nuovo pericolo"]
        self.assertEqual([hazard.name for hazard in self.client.get(reverse("catalog")).context["hazards"]], names)
        self.client.post(reverse("catalog_publish", args=[draft.pk]), {"version": 3})
        self.assertEqual(self.client.post(edit_url, {"version": 3, "severity": "7"}).status_code, 409)
        self.hazard.refresh_from_db()
        copied.refresh_from_db()
        self.assertEqual(self.hazard.severity, Decimal("2"))
        self.assertEqual(copied.severity, Decimal("3.5"))
        self.assertEqual(draft.hazards.get(name="Nuovo pericolo").severity, Decimal("1.25"))
        self.assertNotContains(self.client.get(self.revision_url("revision")), "Nuovo pericolo")
        assessment, revision = services.new_assessment(self.company_a, "Valutazione aggiornata")
        page = self.client.get(reverse("revision", args=[assessment.pk, revision.pk]))
        self.assertEqual([hazard.name for hazard, *_ in page.context["columns"]], names)

    def test_discarding_the_catalog_draft_keeps_the_published_version(self):
        self.client.force_login(self.operator)
        draft = services.start_catalog_draft()
        url = reverse("catalog_discard", args=[draft.pk])
        self.assertContains(self.client.get(url), "Conferma annullamento")
        category = draft.categories.get()
        services.save_catalog_row(draft.pk, 0, None, category.pk, "Modifica provvisoria")
        self.assertEqual(self.client.post(url, {"version": 0}).status_code, 409)
        self.assertRedirects(self.client.post(url, {"version": 1}), reverse("catalog"))
        catalog = Catalog.objects.get(pk=1)
        self.assertEqual(catalog.current, self.v1)
        self.assertIsNone(catalog.draft)
        self.assertFalse(CatalogVersion.objects.filter(pk=draft.pk).exists())
        self.assertEqual(self.v1.hazards.get(), self.hazard)
        self.assertEqual(services.start_catalog_draft().number, draft.number)

    def test_catalog_history_is_read_only_even_with_an_open_draft(self):
        self.client.force_login(self.operator)
        v2 = services.start_catalog_draft()
        services.save_category(v2.pk, 0, v2.categories.get().pk, "Categoria aggiornata")
        services.publish_catalog(v2.pk, 1)
        draft = services.start_catalog_draft()
        catalog_url = reverse("catalog")
        self.assertEqual(self.client.get(catalog_url).context["version"], draft)
        old = self.client.get(catalog_url, {"versione": 1})
        self.assertContains(old, "Categoria campione")
        self.assertNotContains(old, "Categoria aggiornata")
        self.assertNotContains(old, "Aggiorna catalogo")
        self.assertNotContains(old, "Nuovo pericolo")
        self.assertNotContains(old, "Modifica gravità")
        self.assertEqual(list(old.context["versions"]), [draft, v2, self.v1])
        self.assertContains(self.client.get(catalog_url, {"versione": 2}), "Categoria aggiornata")
        self.assertEqual(self.client.get(catalog_url, {"versione": 42}).status_code, 404)

    def test_new_category_includes_a_general_row_without_a_checkbox(self):
        self.client.force_login(self.operator)
        draft = services.start_catalog_draft()
        url = reverse("catalog_category_create", args=[draft.pk])
        self.assertNotContains(self.client.get(url), 'name="general"')
        self.assertRedirects(self.client.post(url, {"version": 0, "name": "Materiali"}), reverse("catalog"))
        category = draft.categories.get(name="Materiali")
        self.assertEqual(list(category.rows.values_list("label", flat=True)), [""])

    def test_probability_editor_opens_first_row_and_identical_values_do_not_write(self):
        self.client.force_login(self.operator)
        url = self.revision_url("revision")
        page = self.client.get(url)
        self.assertEqual(page.context["selected"], self.general)
        self.assertNotContains(page, "Apri voce")
        self.assertEqual(self.client.get(url, {"voce": self.detail.pk}).context["selected"], self.detail)
        self.assertEqual(self.save(self.general, "", 0).status_code, 302)
        self.assertEqual(self.save(self.general, "0", 0).status_code, 302)
        self.assertEqual(self.save(self.general, "00,000", 1).status_code, 302)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.edit_version, 1)
        error = self.save(self.general, "-1", 1)
        self.assertContains(error, 'data-saved-value="0"', status_code=400)

    def test_v1_checks_exact_boundaries(self):
        expected = [
            (None, None, ""), ("0", "0", ""), ("0.999999999999", "0.999999999999", ""),
            ("1", "1", "low"), ("2", "2", "low"), ("2.5", "2.5", ""),
            ("3", "3", "medium"), ("7", "7", "medium"), ("7.000000000001", "7.000000000001", "high"),
        ]
        for probability, value, band in expected:
            with self.subTest(probability=probability):
                actual = calculate_v1(Decimal(1), Decimal(probability) if probability is not None else None)
                self.assertEqual(actual, (Decimal(value) if value is not None else None, band))


class ConcurrentDraftTest(TransactionTestCase):
    def test_only_one_save_can_use_the_same_version(self):
        _, general, _, hazard = initial_catalog()
        assessment, draft = services.new_assessment(Company.objects.create(name="Alfa"), "Visita")
        ready = Barrier(2, timeout=5)

        def save(value):
            try:
                ready.wait()
                services.save_probabilities(assessment.pk, draft.pk, 0, general.pk, {hazard.pk: Decimal(value)})
            except services.Conflict:
                return None
            finally:
                connections.close_all()
            return Decimal(value)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, (1, 2)))
        self.assertEqual(results.count(None), 1)
        self.assertIn(draft.probabilities.get().value, results)
        draft.refresh_from_db()
        self.assertEqual(draft.edit_version, 1)
