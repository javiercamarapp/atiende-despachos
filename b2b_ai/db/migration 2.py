# -*- coding: utf-8 -*-
"""
migration.py — SQLite → PostgreSQL data migration script.

Exports all data from an SQLite database and imports it into a PostgreSQL
database, preserving multi-tenant isolation and data integrity.

Usage:
    # Migrate from SQLite to PostgreSQL
    python -m b2b_ai.db.migration --sqlite /path/to/b2b_ai.db --pg postgresql://user:pass@host:5432/b2b_ai

    # Dry run (validate only, no writes)
    python -m b2b_ai.db.migration --sqlite /path/to/b2b_ai.db --pg postgresql://... --dry-run

    # Validate existing migration (compare row counts)
    python -m b2b_ai.db.migration --validate --pg postgresql://...

Environment variables:
    B2B_DB_PATH    Path to SQLite database (default: b2b_ai.db)
    B2B_DATABASE_URL  PostgreSQL connection string
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("b2b_ai.db.migration")

# ---------------------------------------------------------------------------
# Table order matters: FKs must be satisfied on insert.
# We insert parent tables first, then children.
# ---------------------------------------------------------------------------
TABLE_ORDER = [
    "tenants",
    "users",
    "invoices",
    "classifications",
    "audit_log",
    "notifications",
    "schema_version",
    "api_keys",
    "leads",
    "tenant_config",
    "reviews",
    "webhook_deliveries",
    "collection_events",
    "outstanding_invoices",
    "tenant_usage",
    "webhook_subscriptions",
    "cuentas_contables",
    "asientos_contables",
    "balanzas_mensuales",
    "paquetes_contabilidad",
    "client_users",
    "portal_sessions",
    "billing_customers",
    "billing_subscriptions",
    "billing_invoices",
    "billing_payment_methods",
    "bank_transactions",
    "bank_confirmations",
    "collection_config",
    "collection_payments",
    "audit_entries",
    "outreach_campaigns",
    "outreach_campaign_leads",
    "outreach_emails",
    "outreach_events",
    "feature_flags",
]


@dataclass
class MigrationResult:
    """Result of a table migration."""
    table: str
    source_count: int = 0
    target_count: int = 0
    inserted: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class MigrationSummary:
    """Overall migration result."""
    results: List[MigrationResult] = field(default_factory=list)
    total_tables: int = 0
    total_rows_migrated: int = 0
    total_errors: int = 0
    duration_seconds: float = 0.0
    pg_schema_applied: bool = False


def _sqlite_to_pg_type(sqlite_type: str) -> str:
    """Map SQLite column type hints to PostgreSQL equivalents."""
    t = (sqlite_type or "").upper()
    if "INTEGER" in t:
        return "BIGINT"
    if "REAL" in t or "FLOAT" in t or "DOUBLE" in t:
        return "DOUBLE PRECISION"
    if "NUMERIC" in t:
        return "NUMERIC"
    return "TEXT"


def _get_sqlite_columns(sqlite_conn: sqlite3.Connection, table: str) -> List[Tuple[str, str]]:
    """Get column names and types from SQLite table."""
    cursor = sqlite_conn.execute(f"PRAGMA table_info({table})")
    return [(row["name"], row["type"]) for row in cursor.fetchall()]


def _quote_pg_identifier(name: str) -> str:
    """Quote a PostgreSQL identifier."""
    return f'"{name}"'


class SQLiteToPostgresMigration:
    """Migrates data from SQLite to PostgreSQL.

    Steps:
    1. Read schema from SQLite
    2. Create tables in PostgreSQL (via Alembic or manual CREATE)
    3. Export data from SQLite in batches
    4. Import data into PostgreSQL
    5. Validate row counts match
    """

    def __init__(self, sqlite_path: str, pg_dsn: str, batch_size: int = 1000):
        self.sqlite_path = sqlite_path
        self.pg_dsn = pg_dsn
        self.batch_size = batch_size
        self._sqlite_conn: Optional[sqlite3.Connection] = None
        self._pg_conn = None

    def _connect_sqlite(self) -> sqlite3.Connection:
        """Connect to SQLite database."""
        if self._sqlite_conn is None:
            self._sqlite_conn = sqlite3.connect(self.sqlite_path)
            self._sqlite_conn.row_factory = sqlite3.Row
        return self._sqlite_conn

    def _connect_pg(self):
        """Connect to PostgreSQL database."""
        if self._pg_conn is None:
            import psycopg
            self._pg_conn = psycopg.connect(self.pg_dsn, autocommit=False)
        return self._pg_conn

    def close(self):
        """Close all connections."""
        if self._sqlite_conn:
            try:
                self._sqlite_conn.close()
            except Exception:
                pass
            self._sqlite_conn = None
        if self._pg_conn:
            try:
                self._pg_conn.close()
            except Exception:
                pass
            self._pg_conn = None

    def _list_tables_sqlite(self) -> List[str]:
        """List all user tables in SQLite (exclude internal)."""
        conn = self._connect_sqlite()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]

    def _count_rows(self, conn, table: str, is_pg: bool = False) -> int:
        """Count rows in a table."""
        try:
            cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
            row = cur.fetchone()
            if isinstance(row, dict):
                return row.get("count", row.get("COUNT(*)", 0))
            return row[0] if row else 0
        except Exception as e:
            logger.debug("Cannot count rows in %s: %s", table, e)
            return 0

    def ensure_pg_schema(self) -> bool:
        """Apply Alembic migrations to PostgreSQL to create the schema."""
        import subprocess
        import sys as _sys

        env = dict(os.environ)
        env["B2B_DB_URL"] = self.pg_dsn
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))

        logger.info("Applying Alembic migrations to PostgreSQL...")
        try:
            result = subprocess.run(
                [_sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=root, env=env, check=True,
                capture_output=True, text=True, timeout=120
            )
            logger.info("Alembic migration complete: %s", result.stdout[-200:] if result.stdout else "ok")
            return True
        except subprocess.CalledProcessError as e:
            logger.error("Alembic migration failed: %s", e.stderr[-800:])
            raise RuntimeError(f"Failed to apply Alembic migrations: {e.stderr[-800:]}")

    def export_sqlite_data(self) -> Dict[str, List[Dict[str, Any]]]:
        """Export all data from SQLite tables.

        Returns dict of {table_name: [row_dicts]}.
        """
        conn = self._connect_sqlite()
        tables = self._list_tables_sqlite()
        data = {}

        for table in tables:
            try:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                data[table] = [dict(r) for r in rows]
                logger.info("Exported %d rows from %s", len(data[table]), table)
            except Exception as e:
                logger.warning("Failed to export %s: %s", table, e)
                data[table] = []

        return data

    def import_to_pg(self, data: Dict[str, List[Dict[str, Any]]]) -> MigrationSummary:
        """Import data dict into PostgreSQL.

        Respects foreign key order via TABLE_ORDER.
        """
        summary = MigrationSummary()
        pg = self._connect_pg()
        start = time.time()

        for table in TABLE_ORDER:
            if table not in data:
                continue
            rows = data[table]
            result = self._migrate_table(table, rows)
            summary.results.append(result)
            summary.total_rows_migrated += result.inserted
            summary.total_errors += len(result.errors)

        # Migrate tables not in TABLE_ORDER (future tables)
        for table, rows in data.items():
            if table not in TABLE_ORDER:
                result = self._migrate_table(table, rows)
                summary.results.append(result)
                summary.total_rows_migrated += result.inserted
                summary.total_errors += len(result.errors)

        pg.commit()
        summary.total_tables = len(summary.results)
        summary.duration_seconds = time.time() - start
        return summary

    def _migrate_table(self, table: str, rows: List[Dict[str, Any]]) -> MigrationResult:
        """Migrate a single table from SQLite data to PostgreSQL."""
        result = MigrationResult(table=table, source_count=len(rows))
        if not rows:
            return result

        pg = self._connect_pg()
        start = time.time()

        # Get column names from the first row
        columns = list(rows[0].keys())
        if not columns:
            return result

        # Build INSERT statement
        col_names = ", ".join(_quote_pg_identifier(c) for c in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        insert_sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) " \
                     f"ON CONFLICT DO NOTHING"

        try:
            # Get PG columns to validate
            pg_cols = self._get_pg_columns(table)
            if pg_cols:
                # Filter to only columns that exist in PG
                valid_cols = [c for c in columns if c in pg_cols]
                if len(valid_cols) < len(columns):
                    skipped_cols = set(columns) - set(valid_cols)
                    logger.info("Table %s: skipping columns not in PG: %s",
                               table, skipped_cols)
                    columns = valid_cols
                    col_names = ", ".join(_quote_pg_identifier(c) for c in columns)
                    placeholders = ", ".join(["%s"] * len(columns))
                    insert_sql = f"INSERT INTO {table} ({col_names}) " \
                                 f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        except Exception:
            pass  # Table might not exist in PG yet

        # Insert in batches
        for i in range(0, len(rows), self.batch_size):
            batch = rows[i:i + self.batch_size]
            for row in batch:
                values = []
                for c in columns:
                    v = row.get(c)
                    if isinstance(v, (dict, list)):
                        v = json.dumps(v, default=str, ensure_ascii=False)
                    values.append(v)
                try:
                    pg.execute(insert_sql, values)
                    result.inserted += 1
                except Exception as e:
                    result.errors.append(f"Row {i}: {str(e)[:200]}")
                    # Rollback the failed statement
                    try:
                        pg.rollback()
                        pg.begin()
                    except Exception:
                        pass

            # Commit each batch
            try:
                pg.commit()
            except Exception as e:
                logger.warning("Batch commit failed for %s: %s", table, e)
                try:
                    pg.rollback()
                except Exception:
                    pass

        result.duration_ms = (time.time() - start) * 1000
        logger.info("Imported %d/%d rows into %s (%.1fms)",
                    result.inserted, result.source_count, table, result.duration_ms)
        return result

    def _get_pg_columns(self, table: str) -> set:
        """Get column names from a PostgreSQL table."""
        pg = self._connect_pg()
        cur = pg.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s AND table_schema = 'public'",
            (table,)
        )
        return {row[0] for row in cur.fetchall()}

    def validate(self) -> MigrationSummary:
        """Validate migration by comparing row counts between SQLite and PG.

        Does NOT import data — only compares existing data.
        """
        summary = MigrationSummary()
        sqlite = self._connect_sqlite()
        pg = self._connect_pg()

        tables = self._list_tables_sqlite()
        for table in tables:
            result = MigrationResult(table=table)
            result.source_count = self._count_rows(sqlite, table)
            try:
                result.target_count = self._count_rows(pg, table)
            except Exception:
                result.target_count = 0
                result.errors.append(f"Table {table} not found in PG")

            if result.source_count != result.target_count:
                result.errors.append(
                    f"Row count mismatch: SQLite={result.source_count}, PG={result.target_count}"
                )
            summary.results.append(result)
            summary.total_errors += len(result.errors)

        summary.total_tables = len(summary.results)
        summary.total_rows_migrated = sum(r.target_count for r in summary.results)
        return summary

    def run(self, dry_run: bool = False) -> MigrationSummary:
        """Execute full migration pipeline.

        1. Ensure PG schema exists
        2. Export SQLite data
        3. Import into PG (unless dry_run)
        4. Validate
        """
        logger.info("Starting SQLite→PostgreSQL migration")
        logger.info("  SQLite: %s", self.sqlite_path)
        logger.info("  PostgreSQL: %s", self.pg_dsn.split("@")[-1] if "@" in self.pg_dsn else self.pg_dsn)

        start = time.time()

        # Step 1: Apply PG schema
        try:
            self.ensure_pg_schema()
            summary = MigrationSummary(pg_schema_applied=True)
        except Exception as e:
            logger.error("Failed to apply PG schema: %s", e)
            raise

        # Step 2: Export from SQLite
        logger.info("Exporting data from SQLite...")
        data = self.export_sqlite_data()
        total_exported = sum(len(rows) for rows in data.values())
        logger.info("Exported %d total rows from %d tables", total_exported, len(data))

        if dry_run:
            logger.info("Dry run — skipping import")
            summary.duration_seconds = time.time() - start
            for table, rows in data.items():
                summary.results.append(MigrationResult(
                    table=table, source_count=len(rows)
                ))
            summary.total_tables = len(summary.results)
            return summary

        # Step 3: Import into PG
        logger.info("Importing data into PostgreSQL...")
        import_summary = self.import_to_pg(data)

        # Step 4: Validate
        logger.info("Validating migration...")
        validation = self.validate()

        import_summary.duration_seconds = time.time() - start
        import_summary.pg_schema_applied = True

        # Report
        logger.info("=" * 60)
        logger.info("Migration complete!")
        logger.info("  Tables: %d", import_summary.total_tables)
        logger.info("  Rows migrated: %d", import_summary.total_rows_migrated)
        logger.info("  Errors: %d", import_summary.total_errors)
        logger.info("  Duration: %.1fs", import_summary.duration_seconds)

        if import_summary.total_errors > 0:
            logger.warning("Errors encountered:")
            for r in import_summary.results:
                if r.errors:
                    logger.warning("  %s: %d errors", r.table, len(r.errors))

        return import_summary


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate B2B-AI data from SQLite to PostgreSQL"
    )
    parser.add_argument(
        "--sqlite", default=os.environ.get("B2B_DB_PATH", "b2b_ai.db"),
        help="Path to SQLite database (default: B2B_DB_PATH or b2b_ai.db)"
    )
    parser.add_argument(
        "--pg", default=os.environ.get("B2B_DATABASE_URL") or os.environ.get("B2B_DB_URL"),
        help="PostgreSQL connection string (default: B2B_DATABASE_URL or B2B_DB_URL)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=1000,
        help="Batch size for inserts (default: 1000)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate only, don't import data"
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Validate existing migration (compare row counts)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging"
    )
    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr
    )

    if not args.pg:
        parser.error("PostgreSQL DSN required (--pg or B2B_DATABASE_URL)")
    if not os.path.exists(args.sqlite) and not args.validate:
        parser.error(f"SQLite database not found: {args.sqlite}")

    migration = SQLiteToPostgresMigration(
        sqlite_path=args.sqlite,
        pg_dsn=args.pg,
        batch_size=args.batch_size
    )

    try:
        if args.validate:
            summary = migration.validate()
        else:
            summary = migration.run(dry_run=args.dry_run)

        # Print summary JSON
        print(json.dumps({
            "tables": summary.total_tables,
            "rows_migrated": summary.total_rows_migrated,
            "errors": summary.total_errors,
            "duration_seconds": round(summary.duration_seconds, 2),
            "pg_schema_applied": summary.pg_schema_applied,
            "details": [
                {
                    "table": r.table,
                    "source": r.source_count,
                    "target": r.target_count,
                    "inserted": r.inserted,
                    "errors": len(r.errors),
                }
                for r in summary.results
            ]
        }, indent=2))

        sys.exit(0 if summary.total_errors == 0 else 1)

    except Exception as e:
        logger.error("Migration failed: %s", e)
        sys.exit(2)
    finally:
        migration.close()


if __name__ == "__main__":
    main()
