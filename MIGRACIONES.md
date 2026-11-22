# Migraciones de Base de Datos - BuscaPieza RD

La base de datos es **PostgreSQL** y el esquema se gestiona con **Flask-Migrate (Alembic)**.
Las migraciones están en `migrations/versions/` y se guardan en git.

## Base de datos nueva

```bash
python scripts/crear_db_postgres.py        # crea usuario y base (una vez)
flask --app "app:create_app" db upgrade    # crea/actualiza las tablas
flask --app "app:create_app" seed          # provincias, categorías, comisiones y admin
```

`iniciar.bat` / `iniciar.sh` ejecutan `db upgrade` y `seed` en cada arranque
(no hacen nada si ya está todo al día). El Dockerfile hace lo mismo.

## Cambiar el esquema

1. Modifica `models.py`.
2. Genera la migración y **revísala** antes de aplicarla:
   ```bash
   flask --app "app:create_app" db migrate -m "agrega campo X a ofertas"
   ```
3. Aplícala:
   ```bash
   flask --app "app:create_app" db upgrade
   ```
4. Sube a git el archivo nuevo de `migrations/versions/`.

### Notas para PostgreSQL

- Los campos `Enum` deben tener `name=` (PostgreSQL crea un tipo por cada uno).
  Para **añadir un valor** a un Enum existente, Alembic no lo detecta: escribe la migración a mano con
  `op.execute("ALTER TYPE estado_oferta ADD VALUE 'nuevo_valor'")`.
- Las búsquedas de texto usan `ILIKE` (sin distinguir mayúsculas).

## Revertir

```bash
flask --app "app:create_app" db downgrade      # deshace la última migración
```

## Respaldo antes de migrar en producción

```bash
pg_dump -h localhost -U buscapieza -Fc buscapieza > respaldo_antes_migracion.dump
# Restaurar:
pg_restore -h localhost -U buscapieza -d buscapieza --clean --if-exists respaldo_antes_migracion.dump
```

## Historial

- `605f108e61c0` — Esquema inicial para PostgreSQL: usuarios, solicitudes (+fotos), ofertas con
  comisión del broker, transacciones, ratings, notificaciones, push tokens y configuración.
