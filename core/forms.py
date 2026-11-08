from django import forms
from django.db import transaction
from django.utils import timezone
from uuid import uuid4

from .models import CashBox, Category, Movement, PaymentCommitment, Project, TreasuryConfiguration


class AuditForm(forms.ModelForm):
    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.request:
            instance.source_ip = getattr(self.request, "audit_ip", None)
            instance.device_info = getattr(self.request, "audit_device", "")
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class CashBoxForm(AuditForm):
    opening_balance = forms.DecimalField(label="Saldo inicial", min_value=0, decimal_places=2, max_digits=12, initial=0)

    class Meta:
        model = CashBox
        fields = ["name", "comment", "is_active"]
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "switch-input"}),
        }

    def save(self, commit=True):
        opening_balance = self.cleaned_data["opening_balance"]
        with transaction.atomic():
            box = super().save(commit=commit)
            if commit and opening_balance > 0 and not box.movements.exists():
                Movement.objects.create(
                    cash_box=box, kind=Movement.Kind.OPENING,
                    amount=opening_balance, source_ip=box.source_ip,
                    device_info=box.device_info, is_demo=box.is_demo,
                )
        return box


class CashBoxUpdateForm(AuditForm):
    class Meta:
        model = CashBox
        fields = ["name", "comment", "is_active"]
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "switch-input"}),
        }


class CashBoxPeriodForm(forms.Form):
    start_date = forms.DateField(label="Desde", widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(label="Hasta", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        if data.get("start_date") and data.get("end_date") and data["end_date"] < data["start_date"]:
            self.add_error("end_date", "La fecha Hasta debe ser igual o posterior a Desde.")
        return data


class MovementForm(AuditForm):
    class Meta:
        model = Movement
        fields = ["cash_box", "category", "amount", "comment"]
        widgets = {"comment": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, kind, request=None, **kwargs):
        self.kind = kind
        super().__init__(*args, request=request, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(kind=kind, is_active=True)
        self.fields["cash_box"].queryset = CashBox.objects.filter(is_active=True, project__isnull=True)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.kind = self.kind
        if self.request:
            instance.source_ip = getattr(self.request, "audit_ip", None)
            instance.device_info = getattr(self.request, "audit_device", "")
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class ProjectForm(AuditForm):
    opening_balance = forms.DecimalField(label="Saldo inicial de la caja", min_value=0, decimal_places=2, max_digits=12, initial=0, required=False)

    class Meta:
        model = Project
        fields = ["name", "goal", "start_date", "expected_end_date"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "expected_end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def save(self, commit=True):
        with transaction.atomic():
            project = super().save(commit=False)
            project.cash_box = CashBox(
                name=f"Proyecto · {project.name}",
                comment="Caja física dedicada al proyecto.",
            )
            if self.request:
                project.source_ip = getattr(self.request, "audit_ip", None)
                project.device_info = getattr(self.request, "audit_device", "")
                project.cash_box.source_ip = project.source_ip
                project.cash_box.device_info = project.device_info
            if commit:
                project_box = project.cash_box
                project_box.save()
                project.cash_box_id = project_box.pk
                project.save()
                opening = self.cleaned_data.get("opening_balance") or 0
                if opening > 0:
                    Movement.objects.create(
                        cash_box=project_box, kind=Movement.Kind.OPENING,
                        amount=opening, source_ip=project.source_ip,
                        device_info=project.device_info,
                    )
                self.save_m2m()
        return project


class ProjectUpdateForm(AuditForm):
    class Meta:
        model = Project
        fields = ["name", "goal", "start_date", "expected_end_date", "actual_end_date"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "expected_end_date": forms.DateInput(attrs={"type": "date"}),
            "actual_end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        data = super().clean()
        if self.instance.status == Project.Status.ACTIVE and data.get("actual_end_date"):
            self.add_error("actual_end_date", "Finalice el proyecto con la acción correspondiente.")
        return data

    def save(self, commit=True):
        with transaction.atomic():
            project = super().save(commit=False)
            if self.request:
                project.source_ip = getattr(self.request, "audit_ip", None)
                project.device_info = getattr(self.request, "audit_device", "")
            if commit:
                project.save()
                project_box = project.cash_box
                project_box.name = f"Proyecto · {project.name}"
                if self.request:
                    project_box.source_ip = getattr(self.request, "audit_ip", None)
                    project_box.device_info = getattr(self.request, "audit_device", "")
                project_box.save()
                self.save_m2m()
            return project


class ContributionForm(AuditForm):
    class Meta:
        model = Movement
        fields = ["contributor_name", "amount", "comment"]
        widgets = {"comment": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, project, request=None, **kwargs):
        self.project = project
        super().__init__(*args, request=request, **kwargs)

    def save(self, commit=True):
        movement = super().save(commit=False)
        movement.kind = Movement.Kind.CONTRIBUTION
        movement.project = self.project
        movement.cash_box = self.project.cash_box
        if self.request:
            movement.source_ip = getattr(self.request, "audit_ip", None)
            movement.device_info = getattr(self.request, "audit_device", "")
        if commit:
            movement.save()
        return movement


class CategoryForm(AuditForm):
    class Meta:
        model = Category
        fields = ["name", "kind", "is_active"]


class TreasuryConfigurationForm(AuditForm):
    class Meta:
        model = TreasuryConfiguration
        fields = ["principal_cash_box"]

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, request=request, **kwargs)
        current_id = self.instance.principal_cash_box_id
        from django.db.models import Q
        allowed = Q(is_active=True)
        if current_id:
            allowed |= Q(pk=current_id)
        self.fields["principal_cash_box"].queryset = CashBox.objects.filter(allowed, project__isnull=True)
        self.fields["principal_cash_box"].empty_label = "Sin caja principal"

    def save(self, commit=True):
        configuration = super().save(commit=False)
        configuration.pk = 1
        if self.request:
            configuration.source_ip = getattr(self.request, "audit_ip", None)
            configuration.device_info = getattr(self.request, "audit_device", "")
        if commit:
            configuration.save()
        return configuration


class CommitmentForm(AuditForm):
    class Meta:
        model = PaymentCommitment
        fields = ["person_name", "amount", "commitment_date", "note"]
        widgets = {
            "commitment_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, project, request=None, **kwargs):
        self.project = project
        super().__init__(*args, request=request, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.project = self.project
        if self.request:
            instance.source_ip = getattr(self.request, "audit_ip", None)
            instance.device_info = getattr(self.request, "audit_device", "")
        if commit:
            instance.save()
        return instance


class CommitmentPaymentForm(forms.Form):
    amount = forms.DecimalField(label="Monto de este pago", min_value=0.01, max_digits=12, decimal_places=2)
    contributor_name = forms.CharField(label="Nombre registrado en el aporte", max_length=120, required=False)
    note = forms.CharField(label="Nota", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    submission_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid4)

    def __init__(self, *args, commitment, **kwargs):
        self.commitment = commitment
        kwargs.setdefault("initial", {})
        kwargs["initial"].setdefault("contributor_name", commitment.person_name)
        super().__init__(*args, **kwargs)


class CompleteProjectForm(forms.Form):
    actual_end_date = forms.DateField(label="Fecha real de finalización", widget=forms.DateInput(attrs={"type": "date"}), initial=timezone.localdate)

    def __init__(self, *args, project, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        if data.get("actual_end_date") and data["actual_end_date"] < self.project.start_date:
            self.add_error("actual_end_date", "La fecha real de finalización no puede preceder al inicio del proyecto.")
        return data
