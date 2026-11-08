from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum


def normalized_category_name(value):
    return " ".join((value or "").casefold().split())


class TrackedModel(models.Model):
    created_at = models.DateTimeField("fecha de registro", auto_now_add=True)
    source_ip = models.GenericIPAddressField("dirección IP", null=True, blank=True, editable=False)
    device_info = models.CharField("datos técnicos del dispositivo", max_length=500, blank=True, editable=False)
    is_demo = models.BooleanField("dato de demostración", default=False, editable=False, db_index=True)

    class Meta:
        abstract = True


class Category(TrackedModel):
    class Kind(models.TextChoices):
        INCOME = "income", "Ingreso"
        EXPENSE = "expense", "Gasto"

    name = models.CharField("nombre", max_length=80)
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices)
    is_active = models.BooleanField("activa", default=True)

    class Meta:
        ordering = ["kind", "name"]
        constraints = [models.UniqueConstraint(fields=["name", "kind"], name="unique_category_name_kind")]
        verbose_name = "categoría"
        verbose_name_plural = "categorías"

    def clean(self):
        super().clean()
        if not self.name or not self.kind:
            return
        normalized = normalized_category_name(self.name)
        if self.pk:
            previous = Category.objects.filter(pk=self.pk).values("name", "kind").first()
            if previous and previous["kind"] == self.kind and normalized_category_name(previous["name"]) == normalized:
                return
        candidates = Category.objects.filter(kind=self.kind).exclude(pk=self.pk)
        if any(normalized_category_name(name) == normalized for name in candidates.values_list("name", flat=True)):
            raise ValidationError({"name": "Ya existe una categoría de este tipo con un nombre equivalente (ignorando mayúsculas y espacios)."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.get_kind_display()})"


class CashBox(TrackedModel):
    name = models.CharField("nombre", max_length=100, unique=True)
    comment = models.TextField("comentario", blank=True)
    is_active = models.BooleanField("activa", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "caja"
        verbose_name_plural = "cajas"

    @property
    def balance(self):
        totals = self.movements.aggregate(
            incoming=Sum("amount", filter=~Q(kind=Movement.Kind.EXPENSE)),
            outgoing=Sum("amount", filter=Q(kind=Movement.Kind.EXPENSE)),
        )
        return (totals["incoming"] or Decimal("0.00")) - (totals["outgoing"] or Decimal("0.00"))

    def __str__(self):
        return self.name


class Project(TrackedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Activo"
        COMPLETED = "completed", "Completado"

    name = models.CharField("nombre", max_length=120, unique=True)
    goal = models.DecimalField("meta", max_digits=12, decimal_places=2)
    start_date = models.DateField("fecha de inicio")
    expected_end_date = models.DateField("fecha prevista de finalización", null=True, blank=True)
    actual_end_date = models.DateField("fecha real de finalización", null=True, blank=True)
    status = models.CharField("estado", max_length=10, choices=Status.choices, default=Status.ACTIVE)
    cash_box = models.OneToOneField(CashBox, on_delete=models.PROTECT, related_name="project", verbose_name="caja física")

    class Meta:
        ordering = ["-start_date", "name"]
        constraints = [models.CheckConstraint(condition=models.Q(goal__gt=0), name="project_goal_positive")]
        verbose_name = "proyecto"
        verbose_name_plural = "proyectos"

    def clean(self):
        if self.goal <= 0:
            raise ValidationError({"goal": "La meta debe ser mayor que cero."})
        if self.expected_end_date and self.expected_end_date < self.start_date:
            raise ValidationError({"expected_end_date": "La fecha prevista no puede preceder al inicio."})
        if self.status == self.Status.COMPLETED and not self.actual_end_date:
            raise ValidationError({"actual_end_date": "Indique la fecha real de finalización."})
        if self.actual_end_date and self.actual_end_date < self.start_date:
            raise ValidationError({"actual_end_date": "La fecha real no puede preceder al inicio."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def raised(self):
        return Movement.objects.filter(project=self, kind=Movement.Kind.CONTRIBUTION).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    @property
    def progress_percent(self):
        if not self.goal:
            return 0
        return min(100, int(self.raised * 100 / self.goal))

    @property
    def shortfall(self):
        return max(Decimal("0.00"), self.goal - self.raised)

    def __str__(self):
        return self.name


class TreasuryConfiguration(TrackedModel):
    """A single persisted configuration row for the principal church cash box."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    principal_cash_box = models.OneToOneField(
        CashBox, on_delete=models.PROTECT, related_name="principal_configuration",
        null=True, blank=True, verbose_name="caja principal",
    )

    class Meta:
        verbose_name = "configuración de tesorería"
        verbose_name_plural = "configuración de tesorería"
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="treasury_configuration_singleton")]

    def save(self, *args, **kwargs):
        if self.pk != 1:
            raise ValidationError("Solo se permite una configuración de tesorería.")
        self.full_clean()
        return super().save(*args, **kwargs)


class PaymentCommitment(TrackedModel):
    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "Pendiente"
        PARTIAL = "partial", "Parcial"
        COMPLETED = "completed", "Completado"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="commitments", verbose_name="proyecto")
    person_name = models.CharField("nombre", max_length=120)
    amount = models.DecimalField("monto comprometido", max_digits=12, decimal_places=2)
    commitment_date = models.DateField("fecha del compromiso")
    note = models.TextField("nota", blank=True)

    class Meta:
        ordering = ["commitment_date", "person_name", "pk"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="commitment_amount_positive")]
        verbose_name = "compromiso de pago"
        verbose_name_plural = "compromisos de pago"

    def clean(self):
        if self.amount is None or self.amount <= 0:
            raise ValidationError({"amount": "El monto comprometido debe ser mayor que cero."})
        if self.project_id and self.project.status != Project.Status.ACTIVE:
            raise ValidationError({"project": "No se pueden crear compromisos en un proyecto completado."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def paid_amount(self):
        return self.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    @property
    def pending_amount(self):
        return max(Decimal("0.00"), self.amount - self.paid_amount)

    @property
    def payment_status(self):
        if self.pending_amount == 0:
            return self.PaymentStatus.COMPLETED
        if self.paid_amount > 0:
            return self.PaymentStatus.PARTIAL
        return self.PaymentStatus.PENDING

    @property
    def payment_status_label(self):
        return self.PaymentStatus(self.payment_status).label

    def __str__(self):
        return f"{self.person_name} · {self.amount} · {self.project}"


class Movement(TrackedModel):
    class Kind(models.TextChoices):
        OPENING = "opening", "Saldo inicial"
        INCOME = "income", "Ingreso"
        EXPENSE = "expense", "Gasto"
        CONTRIBUTION = "contribution", "Aporte de proyecto"

    cash_box = models.ForeignKey(CashBox, on_delete=models.PROTECT, related_name="movements", verbose_name="caja")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="movements", null=True, blank=True, verbose_name="categoría")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="contributions", null=True, blank=True, verbose_name="proyecto")
    kind = models.CharField("tipo de movimiento", max_length=15, choices=Kind.choices)
    amount = models.DecimalField("monto", max_digits=12, decimal_places=2)
    comment = models.TextField("comentario", blank=True)
    contributor_name = models.CharField("nombre de quien aporta", max_length=120, blank=True)
    commitment = models.ForeignKey(
        PaymentCommitment, on_delete=models.PROTECT, related_name="payments",
        null=True, blank=True, verbose_name="compromiso vinculado",
    )
    submission_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "movimiento"
        verbose_name_plural = "movimientos"
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="movement_amount_positive")]

    def save(self, *args, **kwargs):
        from django.db import transaction

        with transaction.atomic():
            return self._save_with_financial_checks(*args, **kwargs)

    def _save_with_financial_checks(self, *args, **kwargs):
        self.full_clean()
        if self.pk:
            previous = Movement.objects.get(pk=self.pk)
            if (previous.cash_box_id != self.cash_box_id or previous.kind != self.kind or previous.amount != self.amount
                    or previous.project_id != self.project_id or previous.commitment_id != self.commitment_id):
                raise ValidationError("No se puede modificar el importe, tipo, caja o relación de un movimiento existente.")
        elif self.commitment_id:
            commitment = PaymentCommitment.objects.select_for_update().get(pk=self.commitment_id)
            if self.amount > commitment.pending_amount:
                raise ValidationError({"amount": "El pago supera el monto pendiente del compromiso."})
        if self.kind == self.Kind.EXPENSE:
            available = self.cash_box.balance
            if self.pk:
                previous = Movement.objects.get(pk=self.pk)
                if previous.kind == self.Kind.EXPENSE:
                    available += previous.amount
            if available < self.amount:
                raise ValidationError({"amount": "El gasto supera el saldo disponible de la caja."})
        return super().save(*args, **kwargs)

    @property
    def signed_amount(self):
        if self.kind == self.Kind.EXPENSE:
            return -self.amount
        return self.amount

    def clean(self):
        errors = {}
        if self.amount is None or self.amount <= 0:
            errors["amount"] = "El monto debe ser mayor que cero."
        if self.kind == self.Kind.OPENING:
            if self.category_id or self.project_id:
                errors["kind"] = "El saldo inicial no lleva categoría ni proyecto."
        elif self.kind in (self.Kind.INCOME, self.Kind.EXPENSE):
            expected_kind = Category.Kind.INCOME if self.kind == self.Kind.INCOME else Category.Kind.EXPENSE
            if not self.category_id or self.category.kind != expected_kind:
                errors["category"] = "Seleccione una categoría activa del tipo correspondiente."
            elif not self.category.is_active:
                errors["category"] = "La categoría está desactivada."
            if self.project_id:
                errors["project"] = "Use aportes para registrar entradas de proyectos."
        elif self.kind == self.Kind.CONTRIBUTION:
            if not self.project_id or self.category_id:
                errors["project"] = "El aporte debe pertenecer a un proyecto y no lleva categoría."
            elif self.project.status != Project.Status.ACTIVE:
                errors["project"] = "No se pueden registrar aportes a un proyecto completado."
            elif self.cash_box_id != self.project.cash_box_id:
                errors["cash_box"] = "El aporte debe registrarse en la caja del proyecto."
            if self.commitment_id and self.commitment.project_id != self.project_id:
                errors["commitment"] = "El compromiso debe pertenecer al mismo proyecto."
        elif self.commitment_id:
            errors["commitment"] = "Solo los aportes pueden pagar un compromiso."
        if errors:
            raise ValidationError(errors)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los movimientos son parte del historial y no se pueden borrar.")

    def __str__(self):
        return f"{self.get_kind_display()} · {self.amount} · {self.cash_box}"
