from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import CashBox, Category, Movement, Project


class Command(BaseCommand):
    help = "Crea un conjunto identificable de datos ficticios para demostración."
    marker = "[DEMO]"

    @transaction.atomic
    def handle(self, *args, **options):
        if Movement.objects.filter(is_demo=False, project__is_demo=True).exists() or Movement.objects.filter(is_demo=False, cash_box__is_demo=True).exists() or Movement.objects.filter(is_demo=False, category__is_demo=True).exists():
            self.stderr.write(self.style.ERROR("No se pueden crear datos demo: hay registros reales que referencian datos demo."))
            return
        created_categories = {}
        for kind, name in [
            (Category.Kind.INCOME, "Ofrendas"), (Category.Kind.INCOME, "Diezmos"),
            (Category.Kind.INCOME, "Actividades"), (Category.Kind.EXPENSE, "Construcción"),
            (Category.Kind.EXPENSE, "Luz"), (Category.Kind.EXPENSE, "Aseo"),
        ]:
            category, _ = Category.objects.get_or_create(name=f"{self.marker} {name}", kind=kind, defaults={"is_demo": True})
            created_categories[(kind, name)] = category
        boxes = []
        for name, opening in [("Caja principal", "180.00"), ("Caja de actividades", "45.00")]:
            box, made = CashBox.objects.get_or_create(name=f"{self.marker} {name}", defaults={"is_demo": True, "comment": "Registro ficticio para demostración."})
            boxes.append(box)
            if made:
                Movement.objects.create(cash_box=box, kind=Movement.Kind.OPENING, amount=Decimal(opening), comment="Saldo inicial demo", is_demo=True)
        project_box, _ = CashBox.objects.get_or_create(name=f"{self.marker} Proyecto comunitario", defaults={"is_demo": True, "comment": "Caja física demo."})
        project, made = Project.objects.get_or_create(name=f"{self.marker} Proyecto comunitario", defaults={"cash_box": project_box, "goal": Decimal("500.00"), "start_date": timezone.localdate(), "expected_end_date": timezone.localdate() + timedelta(days=90), "is_demo": True})
        income_cat = created_categories[(Category.Kind.INCOME, "Ofrendas")]
        if not Movement.objects.filter(is_demo=True, cash_box=boxes[0], kind=Movement.Kind.INCOME).exists():
            Movement.objects.create(cash_box=boxes[0], category=income_cat, kind=Movement.Kind.INCOME, amount=Decimal("75.00"), comment="Aporte dominical ficticio", is_demo=True)
        if not Movement.objects.filter(is_demo=True, project=project, kind=Movement.Kind.CONTRIBUTION).exists():
            Movement.objects.create(cash_box=project.cash_box, project=project, kind=Movement.Kind.CONTRIBUTION, amount=Decimal("100.00"), contributor_name="Familia Demo", comment="Aporte ficticio", is_demo=True)
        self.stdout.write(self.style.SUCCESS("Datos demo disponibles. Todos los registros propios llevan is_demo=True y el prefijo [DEMO]."))
