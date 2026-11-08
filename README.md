# MiTesorería v0.4

MVP local para registrar movimientos de cajas físicas de una iglesia. Los saldos se calculan desde el historial. Incluye balance de la caja principal, cajas, ingresos, gastos, proyectos, aportes individuales, compromisos de pago y categorías compartidas.

## Ejecutar con Docker Compose

Requisitos: Docker Desktop con Compose.

```powershell
Copy-Item .env.example .env # opcional; puedes cambiar DJANGO_SECRET_KEY
docker compose up --build
```

Compose publica el servicio solo en `127.0.0.1:8000`; abre <http://localhost:8000>. El panel de Django está en <http://localhost:8000/admin/>. Para crear su usuario administrador:

```powershell
docker compose exec web python manage.py createsuperuser
```

SQLite reside en el volumen Docker existente `sqlite_data`, montado en `/data`. El `Dockerfile` ejecuta las migraciones al iniciar el contenedor. Antes de actualizar una base piloto, revisa las migraciones nuevas y respalda el volumen. `docker compose down` conserva la base. No uses `docker compose down -v`: elimina el volumen.

## Funciones v0.4

- Elige una única caja principal en Cajas. El balance, los ingresos y los gastos superiores corresponden exclusivamente a esa caja; los departamentos aparecen en tarjetas separadas.
- Los ingresos y gastos del dashboard muestran el mes actual de la caja principal.
- Los proyectos activos muestran meta, aportes recibidos, porcentaje y faltante; el porcentaje visual se limita a 100% aunque el total real siga visible.
- Las cajas de proyecto se administran desde Proyectos y no aparecen en la lista general de cajas.
- El detalle de caja resume ingresos, gastos, variación e historial para un intervalo inclusivo de fechas; el saldo actual no depende del intervalo.
- Los proyectos existentes se pueden editar sin reemplazar su caja ni perder aportes; el detalle conserva el historial paginado.
- Los compromisos no cambian el balance. Cada pago se vincula explícitamente y produce un movimiento idempotente. Los pagos pueden superar el compromiso: el pendiente queda en cero y el excedente se muestra por separado.
- El detalle de compromiso muestra cada pago, el total acumulado y el pendiente.
- En Ingresos y Gastos, selecciona una caja para consultar su saldo; al guardar se muestra el nuevo saldo.
- Las categorías se comparten entre cajas y se validan ignorando diferencias de mayúsculas y espacios repetidos.

Los movimientos históricos no se editan ni borran desde la aplicación. No se cargaron datos demo adicionales.

## Datos de demostración

La carga es opcional y se puede repetir sin duplicar el conjunto demo:

```powershell
docker compose exec web python manage.py seed_demo
```

Los registros creados por el comando tienen `is_demo=True` y los nombres llevan el prefijo `[DEMO]`.

La limpieza primero muestra una vista previa y no cambia nada:

```powershell
docker compose exec web python manage.py clear_demo
```

Después de revisar el conteo, confirma explícitamente:

```powershell
docker compose exec web python manage.py clear_demo --confirm
```

La eliminación se ejecuta en una transacción. Si un movimiento o proyecto real apunta a una caja, categoría o proyecto demo, la operación se rechaza completa. No ejecutes `clear_demo --confirm` si no quieres borrar los registros demo identificados.

## Desarrollo y pruebas sin Docker

Requiere Python 3.12 o posterior. En PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

La base local se guarda en `data/db.sqlite3`. Para probar y revisar las migraciones:

```powershell
python manage.py test
python manage.py makemigrations --check --dry-run
python manage.py check
```

`manage.py test` crea su propia base temporal y ejecuta las migraciones ahí. Para actualizar el contenedor existente, revisa las migraciones y luego ejecuta `docker compose up --build -d`; no elimines el volumen `sqlite_data`. Esta revisión no requiere migraciones nuevas.

## Reglas básicas

- Montos con dos decimales; no se aceptan montos cero o negativos.
- Los gastos no pueden superar el saldo calculado disponible.
- Cada saldo inicial y aporte se conserva como un movimiento especial del historial.
- Los movimientos no se pueden borrar desde las pantallas de la aplicación.
- Las categorías desactivadas se conservan para mantener legible el historial.
- Se registra fecha, IP de origen y agente de usuario cuando están disponibles.
- Esta fase no incluye cuentas operativas, roles ni publicación pública.
