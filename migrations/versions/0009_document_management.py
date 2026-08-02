"""document_management tables (PostgreSQL)

Revision ID: 0009_document_management
Revises: 0008_privacy_consent

Adds persistence tables for the document management module (documents,
document_versions, document_shares). Ids are TEXT (UUID) to preserve the
existing API contract.
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_document_management"
down_revision = "0008_privacy_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False, server_default="otro"),
        sa.Column("content_type", sa.String(), nullable=False,
                  server_default="application/octet-stream"),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(), nullable=False, server_default=""),
        sa.Column("storage_path", sa.String(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("tags", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(), nullable=False, server_default="ACTIVO"),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("idx_documents_tenant", "documents", ["tenant_id"])
    op.create_index("idx_documents_tenant_name", "documents", ["tenant_id", "name"])

    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False, server_default=""),
        sa.Column("storage_path", sa.String(), nullable=False, server_default=""),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("idx_docversions_doc", "document_versions", ["document_id"])
    op.create_index("idx_docversions_doc_ver", "document_versions",
                    ["document_id", "version"])

    op.create_table(
        "document_shares",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("shared_with", sa.String(), nullable=False),
        sa.Column("permission", sa.String(), nullable=False, server_default="lectura"),
        sa.Column("token", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=True),
        sa.Column("expires_at", sa.String(), nullable=True),
    )
    op.create_index("idx_docshares_doc", "document_shares", ["document_id"])


def downgrade() -> None:
    op.drop_index("idx_docshares_doc", table_name="document_shares")
    op.drop_table("document_shares")
    op.drop_index("idx_docversions_doc_ver", table_name="document_versions")
    op.drop_index("idx_docversions_doc", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index("idx_documents_tenant_name", table_name="documents")
    op.drop_index("idx_documents_tenant", table_name="documents")
    op.drop_table("documents")
