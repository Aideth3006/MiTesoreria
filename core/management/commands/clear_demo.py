from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import CashBox, Category, Movement, Project


class Command(BaseCommand):
    help = "Muestra los registros demo y, solo con --confirm, los elimina de forma segura."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", action="store_true", help="Confirma la eliminación después de revisar la vista previa.")

    def _preview(self):
        return {
            "aportes y movimientos": Movement.objects.filter(is_demo=True).count(),
            "proyectos": Project.objects.filter(is_demo=True).count(),
            "cajas": CashBox.objects.filter(is_demo=True).count(),
            "categorías": Category.objects.filter(is_demo=True).count(),
        }

    def handle(self, *args, **options):
        counts = self._preview()
        self.stdout.write("Vista previa de registros marcados como demo:")
        for label, count in counts.items():
            self.stdout.write(f"  {label}: {count}")
        if not options["confirm"]:
            self.stdout.write(self.style.WARNING("Sin cambios. Revisa la vista previa y vuelve a ejecutar con --confirm para borrar estos datos demo."))
            return

        with transaction.atomic():
            movements = Movement.objects.filter(is_demo=True)
            projects = Project.objects.filter(is_demo=True)
            boxes = CashBox.objects.filter(is_demo=True)
            categories = Category.objects.filter(is_demo=True)
            # Demo records may not be dependencies of non-demo records. Check every
            # FK/one-to-one relation explicitly before deleting anything.
            references = []
            if Movement.objects.filter(is_demo=False, cash_box__in=boxes).exists():
                references.append("movimientos reales que apuntan a cajas demo")
            if Movement.objects.filter(is_demo=False, category__in=categories).exists():
                references.append("movimientos reales que apuntan a categorías demo")
            if Movement.objects.filter(is_demo=False, project__in=projects).exists():
                references.append("movimientos reales que apuntan a proyectos demo")
            if Project.objects.filter(is_demo=False, cash_box__in=boxes).exists():
                references.append("proyectos reales que apuntan a cajas demo")
            if references:
                raise CommandError("Limpieza cancelada: existen " + ", ".join(references) + ". No se eliminó ningún registro.")
            movements.delete()
            projects.delete()
            boxes.delete()
            categories.delete()
        self.stdout.write(self.style.SUCCESS("Datos demo eliminados; ningún registro real fue modificado."))
