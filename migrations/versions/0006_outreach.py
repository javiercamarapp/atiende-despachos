"""outreach: tablas de outbound email campaigns (PostgreSQL)

Revision ID: 0006_outreach
Revises: 0005_outstanding_unique
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_outreach"
down_revision = "0005_outstanding_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- Outreach (adquisición): campañas, leads, correos, eventos ----
    op.create_table(
        "outreach_campaigns",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sequence_id", sa.BigInteger(), server_default="1",
                  nullable=True),
        sa.Column("status", sa.Text(), server_default="active", nullable=True),
        sa.Column("sender_email", sa.Text(), nullable=True),
        sa.Column("reply_to", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.Column("launched_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("paused_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("idx_outreach_campaigns_tenant", "outreach_campaigns",
                    ["tenant_id"])

    op.create_table(
        "outreach_campaign_leads",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("stage", sa.BigInteger(), server_default="1", nullable=True),
        sa.Column("status", sa.Text(), server_default="queued", nullable=True),
        sa.Column("next_send_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("emails_sent", sa.BigInteger(), server_default="0",
                  nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["campaign_id"], ["outreach_campaigns.id"]),
    )
    op.create_index("idx_outreach_leads_campaign", "outreach_campaign_leads",
                    ["campaign_id"])
    op.create_index("idx_outreach_leads_tenant", "outreach_campaign_leads",
                    ["tenant_id"])
    op.create_index("idx_outreach_leads_campaign_status",
                    "outreach_campaign_leads", ["campaign_id", "status"])

    op.create_table(
        "outreach_emails",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("template", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="sent", nullable=True),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.Column("opened_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("first_clicked_at", sa.TIMESTAMP(timezone=True),
                  nullable=True),
        sa.Column("opened_count", sa.BigInteger(), server_default="0",
                  nullable=True),
        sa.Column("click_count", sa.BigInteger(), server_default="0",
                  nullable=True),
        sa.ForeignKeyConstraint(["lead_id"], ["outreach_campaign_leads.id"]),
    )
    op.create_index("idx_outreach_emails_lead", "outreach_emails", ["lead_id"])
    op.create_index("idx_outreach_emails_campaign", "outreach_emails",
                    ["campaign_id"])
    op.create_index("idx_outreach_emails_tenant", "outreach_emails",
                    ["tenant_id"])

    op.create_table(
        "outreach_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("email_id", sa.BigInteger(), nullable=True),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("link_id", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["email_id"], ["outreach_emails.id"]),
    )
    op.create_index("idx_outreach_events_tenant", "outreach_events",
                    ["tenant_id"])
    op.create_index("idx_outreach_events_email", "outreach_events",
                    ["email_id"])
    op.create_index("idx_outreach_events_lead", "outreach_events", ["lead_id"])


def downgrade() -> None:
    op.drop_table("outreach_events")
    op.drop_table("outreach_emails")
    op.drop_table("outreach_campaign_leads")
    op.drop_table("outreach_campaigns")
