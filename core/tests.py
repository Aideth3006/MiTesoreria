from datetime import date
from decimal import Decimal
from io import StringIO
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .forms import CashBoxForm, CommitmentPaymentForm, ContributionForm, MovementForm, ProjectForm
from .models import CashBox, Category, Movement, PaymentCommitment, Project, TreasuryConfiguration


class HomePageTests(TestCase):
    def test_home_page_displays_app_name_and_balance(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MiTesorería")
        self.assertContains(response, "Caja principal")

    def test_main_screens_load(self):
        for url_name in ("boxes", "incomes", "expenses", "projects", "settings"):
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)

    def test_dashboard_balance_uses_only_designated_principal_box(self):
        main_box = CashBox.objects.create(name="Caja principal prueba")
        other_box = CashBox.objects.create(name="Caja jóvenes prueba")
        category = Category.objects.get(name="Ofrendas", kind=Category.Kind.INCOME)
        Movement.objects.create(cash_box=main_box, category=category, kind=Movement.Kind.INCOME, amount=Decimal("80.00"))
        Movement.objects.create(cash_box=other_box, category=category, kind=Movement.Kind.INCOME, amount=Decimal("900.00"))
        TreasuryConfiguration.objects.create(pk=1, principal_cash_box=main_box)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "$80,00")
        # The principal balance stays isolated while the secondary box is
        # intentionally shown as its own card on the dashboard.
        self.assertContains(response, "$900,00")
        self.assertContains(response, "Caja jóvenes prueba")
        self.assertEqual(response.context["total"], Decimal("80.00"))
        self.assertEqual(response.context["monthly_income"], Decimal("80.00"))

    def test_dashboard_does_not_choose_a_box_when_principal_is_unset(self):
        CashBox.objects.create(name="Caja cualquiera")
        response = self.client.get(reverse("home"))
        self.assertIsNone(response.context["principal"])
        self.assertContains(response, "Aún no designada")
        self.assertContains(response, "Configurar en Cajas")

    def test_accessibility_controls_and_keyboard_landmarks_are_present(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Saltar al contenido")
        self.assertContains(response, "<main class=\"main-content\"")
        self.assertNotContains(response, "large-text-toggle")

    def test_settings_allow_only_one_principal_box(self):
        first = CashBox.objects.create(name="Principal A")
        second = CashBox.objects.create(name="Principal B")
        TreasuryConfiguration.objects.create(pk=1, principal_cash_box=first)
        config = TreasuryConfiguration.objects.get(pk=1)
        config.principal_cash_box = second
        config.save()
        self.assertEqual(TreasuryConfiguration.objects.count(), 1)
        self.assertEqual(TreasuryConfiguration.objects.get().principal_cash_box, second)

    def test_dashboard_project_cards_use_received_contributions_and_shortfall(self):
        box = CashBox.objects.create(name="Caja de proyecto dashboard")
        project = Project.objects.create(name="Proyecto dashboard", goal=Decimal("100.00"), start_date=date(2026, 1, 1), cash_box=box)
        Movement.objects.create(cash_box=box, project=project, kind=Movement.Kind.CONTRIBUTION, amount=Decimal("40.00"))
        response = self.client.get(reverse("home"))
        self.assertEqual(response.context["active_projects"].get(), project)
        self.assertContains(response, "$40,00")
        self.assertContains(response, "$60,00")
        self.assertContains(response, reverse("project-detail", args=[project.pk]))

    def test_settings_post_persists_principal_box(self):
        box = CashBox.objects.create(name="Caja que será principal")
        response = self.client.post(reverse("boxes"), {"form_type": "principal", "principal_cash_box": box.pk})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TreasuryConfiguration.objects.get(pk=1).principal_cash_box, box)


class FinanceRulesTests(TestCase):
    def setUp(self):
        self.income = Category.objects.get(name="Ofrendas", kind=Category.Kind.INCOME)
        self.expense = Category.objects.get(name="Luz", kind=Category.Kind.EXPENSE)
        self.box = CashBox.objects.create(name="Caja de prueba")

    def test_opening_and_income_increase_balance_and_expense_decreases_it(self):
        Movement.objects.create(cash_box=self.box, kind=Movement.Kind.OPENING, amount=Decimal("100.00"))
        Movement.objects.create(cash_box=self.box, category=self.income, kind=Movement.Kind.INCOME, amount=Decimal("25.50"))
        Movement.objects.create(cash_box=self.box, category=self.expense, kind=Movement.Kind.EXPENSE, amount=Decimal("10.25"))
        self.assertEqual(self.box.balance, Decimal("115.25"))

    def test_expense_cannot_make_balance_negative(self):
        with self.assertRaises(ValidationError):
            Movement.objects.create(cash_box=self.box, category=self.expense, kind=Movement.Kind.EXPENSE, amount=Decimal("1.00"))
        self.assertEqual(self.box.balance, Decimal("0.00"))

    def test_movements_must_have_positive_amount_and_cannot_be_deleted(self):
        with self.assertRaises(ValidationError):
            Movement.objects.create(cash_box=self.box, category=self.income, kind=Movement.Kind.INCOME, amount=Decimal("0.00"))
        opening = Movement.objects.create(cash_box=self.box, kind=Movement.Kind.OPENING, amount=Decimal("1.00"))
        with self.assertRaises(ValidationError):
            opening.delete()

    def test_cash_box_form_records_opening_balance_as_special_movement(self):
        form = CashBoxForm(data={"name": "Caja inicial", "comment": "", "is_active": True, "opening_balance": "35.00"})
        self.assertTrue(form.is_valid(), form.errors)
        box = form.save()
        self.assertEqual(box.balance, Decimal("35.00"))
        self.assertEqual(box.movements.get().kind, Movement.Kind.OPENING)

    def test_movement_form_and_balance_endpoint_use_selected_regular_box(self):
        other = CashBox.objects.create(name="Caja secundaria balance")
        project_box = CashBox.objects.create(name="Caja del proyecto solo")
        Project.objects.create(name="Proyecto caja solo", goal=Decimal("50.00"), start_date=date(2026, 1, 1), cash_box=project_box)
        Movement.objects.create(cash_box=self.box, kind=Movement.Kind.OPENING, amount=Decimal("30.00"))
        Movement.objects.create(cash_box=other, kind=Movement.Kind.OPENING, amount=Decimal("900.00"))
        response = self.client.get(reverse("incomes"), {"cash_box": self.box.pk})
        self.assertEqual(response.context["selected_box"], self.box)
        self.assertEqual(response.context["selected_box"].balance, Decimal("30.00"))
        self.assertEqual(response.context["form"].initial["cash_box"], str(self.box.pk))
        result = self.client.get(reverse("cashbox-balance"), {"cash_box_id": self.box.pk})
        self.assertEqual(result.json()["balance"], "30.00")
        form = MovementForm(kind=Movement.Kind.INCOME)
        self.assertIn(other, form.fields["cash_box"].queryset)
        self.assertNotIn(project_box, form.fields["cash_box"].queryset)

    def test_category_names_are_unique_after_casefold_and_whitespace_normalization(self):
        with self.assertRaises(ValidationError):
            Category.objects.create(name="  ofrendas  ", kind=Category.Kind.INCOME)


class ProjectTests(TestCase):
    def test_project_goal_must_be_positive(self):
        box = CashBox.objects.create(name="Caja de proyecto inválida")
        project = Project(name="Meta inválida", goal=Decimal("0.00"), start_date=date(2026, 1, 1), cash_box=box)
        with self.assertRaises(ValidationError):
            project.save()

    def test_project_form_creates_dedicated_box_and_contribution_once(self):
        form = ProjectForm(data={
            "name": "Techo del templo", "goal": "250.00", "start_date": "2026-11-01",
            "expected_end_date": "2027-02-01", "opening_balance": "20.00",
        })
        self.assertTrue(form.is_valid(), form.errors)
        project = form.save()
        self.assertEqual(project.cash_box.project, project)
        contribution_form = ContributionForm(data={"contributor_name": "Ana", "amount": "50.00", "comment": ""}, project=project)
        self.assertTrue(contribution_form.is_valid(), contribution_form.errors)
        contribution_form.save()
        self.assertEqual(project.contributions.count(), 1)
        self.assertEqual(project.raised, Decimal("50.00"))
        self.assertEqual(project.progress_percent, 20)
        self.assertEqual(project.cash_box.balance, Decimal("70.00"))

    def test_completed_project_rejects_contributions(self):
        box = CashBox.objects.create(name="Caja proyecto")
        project = Project.objects.create(name="Pintura", goal=Decimal("100.00"), start_date=date(2026, 1, 1), cash_box=box)
        project.status = Project.Status.COMPLETED
        project.actual_end_date = date(2026, 2, 1)
        project.save()
        movement = Movement(cash_box=box, project=project, kind=Movement.Kind.CONTRIBUTION, amount=Decimal("10.00"))
        with self.assertRaises(ValidationError):
            movement.save()

    def test_project_detail_shows_real_goal_raised_and_shortfall(self):
        box = CashBox.objects.create(name="Caja de avance")
        project = Project.objects.create(name="Meta del salón", goal=Decimal("100.00"), start_date=date(2026, 1, 1), cash_box=box)
        Movement.objects.create(cash_box=box, project=project, kind=Movement.Kind.CONTRIBUTION, amount=Decimal("125.00"), contributor_name="Sam")
        response = self.client.get(reverse("project-detail", args=[project.pk]))
        self.assertEqual(response.context["project"].raised, Decimal("125.00"))
        self.assertEqual(response.context["project"].shortfall, Decimal("0.00"))
        self.assertEqual(response.context["project"].progress_percent, 100)
        self.assertContains(response, "$125,00")

    def test_commitment_does_not_increase_balance_and_partial_pay_is_idempotent(self):
        box = CashBox.objects.create(name="Caja compromiso")
        project = Project.objects.create(name="Proyecto compromiso", goal=Decimal("200.00"), start_date=date(2026, 1, 1), cash_box=box)
        commitment = PaymentCommitment.objects.create(project=project, person_name="Rosa", amount=Decimal("100.00"), commitment_date=date(2026, 3, 1))
        self.assertEqual(box.balance, Decimal("0.00"))
        self.assertEqual(project.raised, Decimal("0.00"))
        key = uuid4()
        data = {"amount": "35.00", "contributor_name": "Rosa", "note": "Primera parte", "submission_key": str(key)}
        url = reverse("pay-commitment", args=[commitment.pk])
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(box.balance, Decimal("35.00"))
        self.assertEqual(project.raised, Decimal("35.00"))
        self.assertEqual(commitment.payments.count(), 1)
        self.assertEqual(commitment.pending_amount, Decimal("65.00"))
        self.assertEqual(commitment.payment_status, PaymentCommitment.PaymentStatus.PARTIAL)
        self.client.post(url, {**data, "amount": "65.00", "submission_key": str(uuid4())})
        self.assertEqual(commitment.payments.count(), 2)
        self.assertEqual(commitment.pending_amount, Decimal("0.00"))
        self.assertEqual(commitment.payment_status, PaymentCommitment.PaymentStatus.COMPLETED)
        self.assertEqual(box.balance, Decimal("100.00"))

    def test_commitment_rejects_payment_above_pending_amount(self):
        box = CashBox.objects.create(name="Caja límite")
        project = Project.objects.create(name="Proyecto límite", goal=Decimal("200.00"), start_date=date(2026, 1, 1), cash_box=box)
        commitment = PaymentCommitment.objects.create(project=project, person_name="Luis", amount=Decimal("20.00"), commitment_date=date(2026, 4, 1))
        first_payment = Movement(cash_box=box, project=project, commitment=commitment, kind=Movement.Kind.CONTRIBUTION, amount=Decimal("10.00"), contributor_name="Luis")
        first_payment.save()
        response = self.client.post(reverse("pay-commitment", args=[commitment.pk]), {
            "amount": "10.01", "contributor_name": "Luis", "note": "", "submission_key": str(uuid4()),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(commitment.payments.count(), 1)
        self.assertEqual(box.balance, Decimal("10.00"))

    def test_finishing_project_warns_about_pending_commitments(self):
        box = CashBox.objects.create(name="Caja con compromiso pendiente")
        project = Project.objects.create(name="Cierre con pendiente", goal=Decimal("100.00"), start_date=date(2026, 1, 1), cash_box=box)
        PaymentCommitment.objects.create(project=project, person_name="Noemí", amount=Decimal("30.00"), commitment_date=date(2026, 2, 1))
        response = self.client.get(reverse("complete-project", args=[project.pk]))
        self.assertContains(response, "Hay compromisos pendientes")
        self.assertContains(response, "no los borrará ni modificará")

    def test_contribution_history_keeps_each_repeated_name_record(self):
        box = CashBox.objects.create(name="Caja historial")
        project = Project.objects.create(name="Proyecto historial", goal=Decimal("500.00"), start_date=date(2026, 1, 1), cash_box=box)
        for _ in range(52):
            Movement.objects.create(cash_box=box, project=project, kind=Movement.Kind.CONTRIBUTION, amount=Decimal("1.00"), contributor_name="Mismo nombre")
        response = self.client.get(reverse("project-detail", args=[project.pk]))
        self.assertEqual(response.context["contributions_page"].paginator.count, 52)
        self.assertEqual(response.context["contributions_page"].paginator.num_pages, 2)
        summary = response.context["summaries"].get(contributor_name="Mismo nombre")
        self.assertEqual(summary["count"], 52)
        self.assertEqual(summary["total"], Decimal("52.00"))


class ClearDemoSafetyTests(TestCase):
    def test_clear_demo_preview_does_not_delete_any_data(self):
        call_command("seed_demo", stdout=StringIO())
        before = (Movement.objects.count(), CashBox.objects.count(), Project.objects.count(), Category.objects.count())
        output = StringIO()
        call_command("clear_demo", stdout=output)
        after = (Movement.objects.count(), CashBox.objects.count(), Project.objects.count(), Category.objects.count())
        self.assertEqual(before, after)
        self.assertIn("Sin cambios", output.getvalue())

    def test_clear_demo_confirm_deletes_only_demo_data(self):
        call_command("seed_demo", stdout=StringIO())
        real_category = Category.objects.get(name="Ofrendas", kind=Category.Kind.INCOME)
        real_box = CashBox.objects.create(name="Caja real")
        Movement.objects.create(cash_box=real_box, category=real_category, kind=Movement.Kind.INCOME, amount=Decimal("15.00"))
        call_command("clear_demo", confirm=True, stdout=StringIO())
        self.assertEqual(Movement.objects.filter(is_demo=True).count(), 0)
        self.assertTrue(CashBox.objects.filter(pk=real_box.pk, is_demo=False).exists())
        self.assertTrue(Movement.objects.filter(cash_box=real_box, is_demo=False).exists())
        self.assertTrue(Category.objects.filter(pk=real_category.pk, is_demo=False).exists())

    def test_clear_demo_refuses_real_references_and_rolls_back_all_deletes(self):
        call_command("seed_demo", stdout=StringIO())
        demo_box = CashBox.objects.get(name="[DEMO] Caja principal")
        real_category = Category.objects.get(name="Ofrendas", kind=Category.Kind.INCOME)
        Movement.objects.create(cash_box=demo_box, category=real_category, kind=Movement.Kind.INCOME, amount=Decimal("4.00"), is_demo=False)
        demo_counts = (Movement.objects.filter(is_demo=True).count(), CashBox.objects.filter(is_demo=True).count())
        with self.assertRaisesMessage(CommandError, "Limpieza cancelada"):
            call_command("clear_demo", confirm=True, stdout=StringIO())
        self.assertEqual(demo_counts, (Movement.objects.filter(is_demo=True).count(), CashBox.objects.filter(is_demo=True).count()))
        self.assertTrue(Movement.objects.filter(cash_box=demo_box, is_demo=False).exists())
