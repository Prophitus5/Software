# Sistema Biblioteca

Aplicación en español para préstamos y devoluciones de biblioteca pequeña, con Firebird 5 integrado, FastAPI, SQLAlchemy 2 y una interfaz local adaptable a móvil.

## Ejecución local en Windows (sin Docker)

Este es el modo recomendado para la presentación de clase. Requiere Python 3.12+ y Firebird 5 instalado en `C:\Program Files\Firebird\Firebird_5_0`. Se conecta con el motor integrado local, así que no necesita Docker ni un servicio de Firebird en ejecución.

1. Abre PowerShell en la carpeta del proyecto.
2. Ejecuta `Set-ExecutionPolicy -Scope Process Bypass` si Windows bloquea los scripts.
3. Ejecuta `.\iniciar_local.ps1`.
4. Abre <http://127.0.0.1:8000>. La aplicación solo escucha en loopback; otros equipos no pueden conectarse.

El script crea `.env`, instala las dependencias en `.venv`, crea `data/biblioteca.fdb` y arranca FastAPI sobre Firebird integrado. Para detener la aplicación usa Ctrl+C.

### Cuentas de muestra

| Rol | Correo | Contraseña inicial |
| --- | --- | --- |
| Dueño | `dueno@biblioteca.local` | `ChangeMe123!` |
| Bibliotecario | `bibliotecario@biblioteca.local` | `Bibliotecario123!` |
| Trabajador de campo | `reclamador@biblioteca.local` | `Reclamador123!` |

El dueño puede crear más cuentas en **Usuarios y equipo**. El trabajador de campo entra en **Mis visitas** y solo ve las órdenes asignadas a su cuenta. El primer inicio crea libros, lectores, un préstamo vigente y una orden de demostración si la base todavía no tiene esos registros.

Desde el menú lateral puedes abrir **Libros** o **Lectores** y registrarlos con los formularios de la misma pantalla. Las barras de búsqueda filtran el catálogo por código, título o autor, y el directorio por DNI, nombre o teléfono. El buscador superior muestra sugerencias en vivo por palabras. En **Préstamos** puedes filtrar el historial y encontrar rápidamente un libro o lector al escribir en los selectores. La pestaña **Recuperación domiciliaria** concentra asignaciones y reportes de visita; si se recupera el libro, muestra la multa calculada. El dueño registra el cobro desde Préstamos y consulta los ingresos en **Recaudación**.

## Ejecución con Docker (opcional)

1. Copia `.env.example` a `.env` y cambia `SECRET_KEY`, `OWNER_PASSWORD` y la contraseña de Firebird.
2. Ejecuta `docker compose up --build`.
3. Abre <http://localhost:8000>. Usuario dueño: los valores `OWNER_EMAIL` y `OWNER_PASSWORD` de `.env`.
4. La API documentada está en <http://localhost:8000/docs>.

Docker es una alternativa; no se necesita para ejecutar el modo local.

## Inicialización manual

Con la base creada en UTF8, ejecuta en `isql-fb` los archivos `db/01_schema.sql`, `02_generators_triggers.sql`, `03_seed.sql` y `04_indexes.sql`, en ese orden. Para usar Firebird local configura `DB_HOST=localhost`, `DB_PATH=C:/ruta/biblioteca.fdb`. Los scripts de esquema son de instalación inicial; para una base existente crea una migración versionada y respalda antes de aplicarla.

## Reglas y modelo

- Identificadores `BIGINT` se asignan con generadores y triggers Firebird.
- `ACTIVO_KEY` y `ABIERTA_KEY` permiten un solo préstamo activo por ejemplar y una sola orden abierta por préstamo.
- Se guardan el préstamo y su fecha de vencimiento; hoy el plazo configurado inicial es siete días.
- Cada libro representa una copia física; los registros se inactivan, no se borran.
- La multa se calcula por día calendario de retraso, a S/. 1.00 por día.
- Firebird no ofrece índices parciales como PostgreSQL: las columnas calculadas que retornan `NULL` para filas cerradas reproducen esa unicidad.

## Copia de seguridad

Usa `gbak -b -user SYSDBA -password "$DB_PASSWORD" localhost:/firebird/data/biblioteca.fdb biblioteca-$(date +%F).fbk`. Para restaurar, detén la app, crea una base nueva con `gbak -c` y verifica el archivo restaurado antes de volver a abrir el servicio.

## Límites de la primera entrega

Esta versión deja implementadas las entidades y operaciones base para libros, lectores, préstamos, devolución, multas y órdenes con permisos. Debes configurar TLS y `COOKIE_SECURE=true` detrás de un proxy HTTPS en producción. Antes de exponerla públicamente completa una revisión de CSRF, rate limiting, auditoría de cada operación, exportaciones y las pruebas de integración contra la versión exacta de Firebird.
