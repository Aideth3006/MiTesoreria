from decimal import Decimal
from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (CashBoxForm, CashBoxPeriodForm, CashBoxUpdateForm, CategoryForm, CommitmentForm, CommitmentPaymentForm,
                    CompleteProjectForm, ContributionForm, MovementForm, ProjectForm, ProjectUpdateForm,
                    TreasuryConfigurationForm)
from .models import CashBox, Category, Movement, PaymentCommitment, Project, TreasuryConfiguration


def _audit_record(request, record):
    record.source_ip = getattr(request, "audit_ip", None)
    record.device_info = getattr(request, "audit_device", "")
    return record


def dashboard(request):
    configuration = TreasuryConfiguration.objects.select_related("principal_cash_box").filter(pk=1).first()
    principal = None
    if configuration and configuration.principal_cash_box_id:
        principal = CashBox.objects.filter(
            pk=configuration.principal_cash_box_id, project__isnull=True,
        ).first()
    today = timezone.localdate()
    month_start = today.replace(day=1)
    monthly = Movement.objects.none()
    if principal:
        monthly = Movement.objects.filter(cash_box=principal, created_at__date__gte=month_start, created_at__date__lte=today)
    monthly_income = monthly.filter(kind=Movement.Kind.INCOME).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    monthly_expenses = monthly.filter(kind=Movement.Kind.EXPENSE).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    recent = Movement.objects.filter(cash_box=principal).select_related("cash_box", "category", "project")[:8] if principal else []
    active_projects = Project.objects.filter(status=Project.Status.ACTIVE).select_related("cash_box")
    active_boxes = CashBox.objects.filter(is_active=True, project__isnull=True)
    if principal:
        active_boxes = active_boxes.exclude(pk=principal.pk)
    chart_max = max(monthly_income, monthly_expenses, Decimal("1.00"))
    return render(request, "core/dashboard.html", {
        "principal": principal, "total": principal.balance if principal else None,
        "monthly_income": monthly_income, "monthly_expenses": monthly_expenses,
        "recent": recent, "today": today, "month_start": month_start,
        "active_projects": active_projects, "secondary_boxes": active_boxes,
        "project_count": active_projects.count(),
        "completed_project_count": Project.objects.filter(status=Project.Status.COMPLETED).count(),
        "income_chart_height": int(monthly_income * 100 / chart_max),
        "expense_chart_height": int(monthly_expenses * 100 / chart_max),
    })


def box_list(request):
    configuration, _ = TreasuryConfiguration.objects.get_or_create(pk=1)
    creating = request.POST.get("form_type") == "new_box" if request.method == "POST" else False
    designating = request.method == "POST" and request.POST.get("form_type") == "principal"
    box_form = CashBoxForm(request.POST if creating else None, request=request)
    principal_form = TreasuryConfigurationForm(
        request.POST if designating else None,
        instance=configuration, request=request,
    )
    if request.method == "POST" and creating and box_form.is_valid():
        try:
            box_form.save()
        except ValidationError as error:
            box_form.add_error(None, error)
        else:
            messages.success(request, "Caja creada correctamente.")
            return redirect("boxes")
    elif designating and principal_form.is_valid():
        try:
            principal_form.save()
        except ValidationError as error:
            principal_form.add_error(None, error)
        else:
            messages.success(request, "Caja principal actualizada.")
            return redirect("boxes")
    boxes = CashBox.objects.filter(project__isnull=True)
    return render(request, "core/boxes.html", {
        "boxes": boxes, "box_form": box_form, "principal_form": principal_form,
        "configuration": configuration,
    })


def box_edit(request, box_id):
    box = get_object_or_404(CashBox, pk=box_id, project__isnull=True)
    form = CashBoxUpdateForm(request.POST or None, instance=box, request=request)
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Datos de la caja actualizados.")
            return redirect("boxes")
    today = timezone.localdate()
    default_start = today.replace(day=1)
    period_form = CashBoxPeriodForm(request.GET or None, initial={"start_date": default_start, "end_date": today})
    start_date, end_date = default_start, today
    if period_form.is_valid():
        start_date = period_form.cleaned_data["start_date"]
        end_date = period_form.cleaned_data["end_date"]
    period_movements = box.movements.filter(
        created_at__date__gte=start_date, created_at__date__lte=end_date,
    ).select_related("category", "project", "commitment")
    period_income = period_movements.filter(kind=Movement.Kind.INCOME).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    period_expenses = period_movements.filter(kind=Movement.Kind.EXPENSE).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    page = Paginator(period_movements, 25).get_page(request.GET.get("page"))
    return render(request, "core/box_edit.html", {
        "box": box, "form": form, "period_form": period_form,
        "start_date": start_date, "end_date": end_date,
        "period_income": period_income, "period_expenses": period_expenses,
        "period_net": period_income - period_expenses,
        "period_movements": page,
    })


def movement_list(request, kind):
    if kind not in (Movement.Kind.INCOME, Movement.Kind.EXPENSE):
        return HttpResponseNotAllowed(["GET", "POST"])
    selected_id = request.POST.get("cash_box") if request.method == "POST" else request.GET.get("cash_box")
    form_initial = {"cash_box": selected_id} if selected_id and request.method == "GET" else None
    form = MovementForm(request.POST or None, kind=kind, request=request, initial=form_initial)
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f"Movimiento registrado. Nuevo saldo de {form.cleaned_data['cash_box'].name}: ${form.cleaned_data['cash_box'].balance:.2f}.")
            return redirect("incomes" if kind == Movement.Kind.INCOME else "expenses")
    movements = Movement.objects.filter(kind=kind).select_related("cash_box", "category")[:100]
    selected_box = None
    if selected_id:
        selected_box = CashBox.objects.filter(pk=selected_id, is_active=True, project__isnull=True).first()
    return render(request, "core/movements.html", {"form": form, "movements": movements, "kind": kind, "selected_box": selected_box})


def cash_box_balance(request):
    box = get_object_or_404(CashBox, pk=request.GET.get("cash_box_id"), is_active=True, project__isnull=True)
    return JsonResponse({"balance": f"{box.balance:.2f}"})


def project_list(request):
    form = ProjectForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except (ValidationError, IntegrityError) as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Proyecto y caja física asociada creados.")
            return redirect("projects")
    projects = Project.objects.select_related("cash_box")
    active_projects = projects.filter(status=Project.Status.ACTIVE)
    completed_projects = projects.filter(status=Project.Status.COMPLETED)
    return render(request, "core/projects.html", {"active_projects": active_projects, "completed_projects": completed_projects, "form": form})


def project_edit(request, project_id):
    project = get_object_or_404(Project.objects.select_related("cash_box"), pk=project_id)
    form = ProjectUpdateForm(request.POST or None, instance=project, request=request)
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except (ValidationError, IntegrityError) as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Proyecto actualizado; se conservaron su caja y su historial.")
            return redirect("project-detail", project_id=project.pk)
    return render(request, "core/project_edit.html", {"project": project, "form": form})


def project_detail(request, project_id):
    project = get_object_or_404(Project.objects.select_related("cash_box"), pk=project_id)
    contributions = project.contributions.filter(kind=Movement.Kind.CONTRIBUTION).select_related("commitment")
    paginator = Paginator(contributions, 50)
    page = paginator.get_page(request.GET.get("page"))
    summaries = contributions.values("contributor_name").annotate(total=Sum("amount"), count=Count("id")).order_by("-total", "contributor_name")
    commitments = project.commitments.all()
    for commitment in commitments:
        commitment.status_label = commitment.payment_status_label
        accumulated = Decimal("0.00")
        commitment.payment_history_rows = []
        for payment in commitment.payments.order_by("created_at", "pk"):
            accumulated += payment.amount
            commitment.payment_history_rows.append({
                "payment": payment,
                "accumulated": accumulated,
                "pending": max(Decimal("0.00"), commitment.amount - accumulated),
            })
    commitment_form = CommitmentForm(request.POST or None, project=project, request=request, prefix="commitment")
    if request.method == "POST" and project.status == Project.Status.ACTIVE and request.POST.get("action") == "add_commitment" and commitment_form.is_valid():
        try:
            commitment_form.save()
        except ValidationError as error:
            commitment_form.add_error(None, error)
        else:
            messages.success(request, "Compromiso registrado; aún no afecta los saldos.")
            return redirect("project-detail", project_id=project.pk)
    return render(request, "core/project_detail.html", {
        "project": project, "contributions_page": page, "summaries": summaries,
        "commitments": commitments, "commitment_form": commitment_form,
        "total_committed": commitments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        "total_paid": sum((item.paid_amount for item in commitments), Decimal("0.00")),
        "total_pending": sum((item.pending_amount for item in commitments), Decimal("0.00")),
    })


def contribute(request, project_id):
    project = get_object_or_404(Project.objects.select_related("cash_box"), pk=project_id)
    form = ContributionForm(request.POST or None, project=project, request=request)
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f"Aporte registrado. Nuevo saldo de la caja: ${project.cash_box.balance:.2f}.")
            return redirect("project-detail", project_id=project.pk)
    return render(request, "core/contribute.html", {"project": project, "form": form})


def pay_commitment(request, commitment_id):
    commitment = get_object_or_404(PaymentCommitment.objects.select_related("project", "project__cash_box"), pk=commitment_id)
    form = CommitmentPaymentForm(request.POST or None, commitment=commitment)
    accumulated = Decimal("0.00")
    payment_history = []
    for payment in commitment.payments.order_by("created_at", "pk"):
        accumulated += payment.amount
        payment_history.append({
            "payment": payment, "accumulated": accumulated,
            "pending": max(Decimal("0.00"), commitment.amount - accumulated),
        })
    if request.method == "POST" and form.is_valid():
        key = form.cleaned_data["submission_key"]
        existing = Movement.objects.filter(submission_key=key).first()
        if existing:
            if existing.commitment_id != commitment.pk:
                form.add_error(None, "Esta solicitud ya se utilizó para otro pago.")
            else:
                messages.info(request, "Este pago ya había sido registrado; no se duplicó.")
                return redirect("project-detail", project_id=commitment.project_id)
        else:
            try:
                with transaction.atomic():
                    locked = PaymentCommitment.objects.select_for_update().get(pk=commitment.pk)
                    Movement.objects.create(
                        cash_box=locked.project.cash_box, project=locked.project, commitment=locked,
                        kind=Movement.Kind.CONTRIBUTION, amount=form.cleaned_data["amount"],
                        contributor_name=form.cleaned_data["contributor_name"], comment=form.cleaned_data["note"],
                        submission_key=key, source_ip=getattr(request, "audit_ip", None),
                        device_info=getattr(request, "audit_device", ""),
                    )
            except ValidationError as error:
                form.add_error(None, error)
            except IntegrityError:
                existing = Movement.objects.filter(submission_key=key).first()
                if existing and existing.commitment_id == commitment.pk:
                    messages.info(request, "Este pago ya había sido registrado; no se duplicó.")
                    return redirect("project-detail", project_id=commitment.project_id)
                form.add_error(None, "No se pudo registrar el pago. Actualiza la página e inténtalo nuevamente.")
            else:
                messages.success(request, f"Pago aplicado. Pendiente: ${locked.pending_amount:.2f}; excedente: ${locked.excess_amount:.2f}.")
                return redirect("project-detail", project_id=commitment.project_id)
    return render(request, "core/pay_commitment.html", {"commitment": commitment, "form": form, "payment_history": payment_history})


def complete_project(request, project_id):
    project = get_object_or_404(Project, pk=project_id, status=Project.Status.ACTIVE)
    form = CompleteProjectForm(request.POST or None, project=project)
    if request.method == "POST" and form.is_valid():
        project.status = Project.Status.COMPLETED
        project.actual_end_date = form.cleaned_data["actual_end_date"]
        _audit_record(request, project).save(update_fields=["status", "actual_end_date", "source_ip", "device_info"])
        messages.success(request, "Proyecto finalizado; su historial permanece disponible.")
        return redirect("projects")
    pending_commitments = [item for item in project.commitments.all() if item.pending_amount > 0]
    return render(request, "core/complete_project.html", {"project": project, "form": form, "pending_commitments": pending_commitments})


def settings_view(request):
    form = CategoryForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Categoría guardada.")
            return redirect("settings")
    return render(request, "core/settings.html", {"categories": Category.objects.all(), "form": form})


def toggle_category(request, category_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    category = get_object_or_404(Category, pk=category_id)
    category.is_active = not category.is_active
    _audit_record(request, category).save(update_fields=["is_active", "source_ip", "device_info"])
    messages.success(request, "Estado de categoría actualizado.")
    return redirect("settings")


