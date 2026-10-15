"""Małe migracje zgodne wstecznie dla instalacji bez Alembic."""

from sqlalchemy import inspect


COLUMNS = {
    "projects": {
        "structure_type": "VARCHAR(160) NOT NULL DEFAULT 'tracker'",
        "archived": "BOOLEAN NOT NULL DEFAULT 0",
        "archived_at": "DATETIME NULL",
    },
    "construction_rows": {
        "template_id": "INTEGER NULL REFERENCES material_templates(id) ON DELETE SET NULL",
        "variant_name": "VARCHAR(120) NOT NULL DEFAULT ''",
        "specification": "TEXT NOT NULL DEFAULT ''",
        "material_quantities_json": "TEXT NOT NULL DEFAULT '{}'",
        "auto_generated": "BOOLEAN NOT NULL DEFAULT 0",
        "active": "BOOLEAN NOT NULL DEFAULT 1",
        "variant_ordinal": "INTEGER NOT NULL DEFAULT 0",
        "sort_order": "INTEGER NOT NULL DEFAULT 0",
    },
    "work_logs": {
        "qc_notes": "TEXT NOT NULL DEFAULT ''",
        "row_id": "INTEGER NULL REFERENCES construction_rows(id) ON DELETE SET NULL",
    },
}


def ensure_schema_columns(engine) -> None:
    """Dodaje wyłącznie brakujące kolumny, zachowując istniejące rekordy."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, definitions in COLUMNS.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspect(engine).get_columns(table)}
            for name, definition in definitions.items():
                if name not in existing:
                    sql_definition = definition
                    if engine.dialect.name == "postgresql":
                        sql_definition = sql_definition.replace("BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE").replace("DATETIME", "TIMESTAMP")
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {sql_definition}")
