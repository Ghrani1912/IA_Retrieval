"""Initial schema — all 6 tables from design.md section 3.1

Revision ID: 0001
Revises:
Create Date: 2026-08-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # sources
    # ------------------------------------------------------------------
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ia_identifier", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "source_type",
            sa.Text(),
            nullable=False,
            server_default="metadata_only",
        ),
        sa.Column("title", sa.Text()),
        sa.Column("author", sa.Text()),
        sa.Column("publisher", sa.Text()),
        sa.Column("pub_date", sa.Date()),
        sa.Column("pub_date_raw", sa.Text()),   # raw IA string before parsing
        sa.Column("language", sa.Text()),
        sa.Column("subject", sa.ARRAY(sa.Text())),
        sa.Column("collection", sa.Text()),
        sa.Column("ia_url", sa.Text()),
        sa.Column("is_open_access", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_check_constraint(
        "ck_sources_source_type",
        "sources",
        "source_type IN ('book','paper','gov_doc','magazine','newspaper',"
        "'website','metadata_only','fetch_failed','index_failed')",
    )

    # ------------------------------------------------------------------
    # chunks
    # ------------------------------------------------------------------
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_or_section", sa.Text()),
        sa.Column("embedding_id", sa.Text()),
        sa.Column("capture_timestamp", sa.TIMESTAMP(timezone=True)),
        sa.Column("char_range_start", sa.Integer(), nullable=False),
        sa.Column("char_range_end", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_chunks_source_id", "chunks", ["source_id"])
    op.create_index("idx_chunks_capture_timestamp", "chunks", ["capture_timestamp"])

    # ------------------------------------------------------------------
    # website_snapshots
    # ------------------------------------------------------------------
    op.create_table(
        "website_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("snapshot_timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("digest", sa.Text()),
        sa.Column("fetched_flag", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fetched_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("url", "snapshot_timestamp", name="uq_snapshot_url_ts"),
    )
    op.create_index("idx_snapshots_domain", "website_snapshots", ["domain"])
    op.create_index(
        "idx_snapshots_domain_fetched",
        "website_snapshots",
        ["domain", "fetched_flag"],
    )

    # ------------------------------------------------------------------
    # evidence_citations
    # ------------------------------------------------------------------
    op.create_table(
        "evidence_citations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("answer_id", sa.Text(), nullable=False),
        sa.Column(
            "chunk_id",
            sa.Integer(),
            sa.ForeignKey("chunks.id"),
            nullable=False,
        ),
        sa.Column("confidence_label", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_check_constraint(
        "ck_citations_confidence_label",
        "evidence_citations",
        "confidence_label IN ('directly_verified','inferred','unknown')",
    )
    op.create_index("idx_citations_answer_id", "evidence_citations", ["answer_id"])

    # ------------------------------------------------------------------
    # ingestion_jobs
    # ------------------------------------------------------------------
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Text(), primary_key=True),   # UUID
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("date_range_from", sa.Date()),
        sa.Column("date_range_to", sa.Date()),
        sa.Column("source_type", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("sources_total", sa.Integer()),
        sa.Column("sources_done", sa.Integer(), server_default="0"),
        sa.Column("chunks_created", sa.Integer(), server_default="0"),
        sa.Column("error_step", sa.Text()),
        sa.Column("error_msg", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_check_constraint(
        "ck_jobs_status",
        "ingestion_jobs",
        "status IN ('queued','running','completed','failed')",
    )

    # ------------------------------------------------------------------
    # eval_runs
    # ------------------------------------------------------------------
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("config_name", sa.Text(), nullable=False),
        sa.Column("recall_10", sa.Float()),
        sa.Column("precision_10", sa.Float()),
        sa.Column("mrr", sa.Float()),
        sa.Column("ndcg_10", sa.Float()),
        sa.Column("citation_correctness", sa.Float()),
        sa.Column("query_count", sa.Integer()),
        sa.Column(
            "run_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("eval_runs")
    op.drop_table("ingestion_jobs")
    op.drop_index("idx_citations_answer_id", "evidence_citations")
    op.drop_table("evidence_citations")
    op.drop_index("idx_snapshots_domain_fetched", "website_snapshots")
    op.drop_index("idx_snapshots_domain", "website_snapshots")
    op.drop_table("website_snapshots")
    op.drop_index("idx_chunks_capture_timestamp", "chunks")
    op.drop_index("idx_chunks_source_id", "chunks")
    op.drop_table("chunks")
    op.drop_table("sources")
