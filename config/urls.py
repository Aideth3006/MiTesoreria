from django.contrib import admin
from django.urls import path

from core import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.dashboard, name="home"),
    path("cajas/", views.box_list, name="boxes"),
    path("cajas/<int:box_id>/editar/", views.box_edit, name="box-edit"),
    path("ingresos/", lambda request: views.movement_list(request, "income"), name="incomes"),
    path("gastos/", lambda request: views.movement_list(request, "expense"), name="expenses"),
    path("cajas/saldo/", views.cash_box_balance, name="cashbox-balance"),
    path("proyectos/", views.project_list, name="projects"),
    path("proyectos/<int:project_id>/", views.project_detail, name="project-detail"),
    path("proyectos/<int:project_id>/editar/", views.project_edit, name="project-edit"),
    path("proyectos/<int:project_id>/aportes/", views.contribute, name="contribute"),
    path("compromisos/<int:commitment_id>/pagar/", views.pay_commitment, name="pay-commitment"),
    path("proyectos/<int:project_id>/finalizar/", views.complete_project, name="complete-project"),
    path("configuracion/", views.settings_view, name="settings"),
    path("configuracion/categorias/<int:category_id>/estado/", views.toggle_category, name="toggle-category"),
]
