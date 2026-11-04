"""Persistent research queue and evidence-backed topic decisions."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'

def upgrade():
    op.create_table('analysis_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('digest', sa.String(64), unique=True, nullable=False),
        sa.Column('is_demo', sa.Boolean, nullable=False), sa.Column('engine', sa.String(20), nullable=False),
        sa.Column('status', sa.String(30), nullable=False), sa.Column('stage', sa.String(100), nullable=False),
        sa.Column('input_data', sa.JSON, nullable=False), sa.Column('weights', sa.JSON, nullable=False),
        sa.Column('provider_config', sa.JSON, nullable=False), sa.Column('result', sa.JSON, nullable=False),
        sa.Column('error', sa.Text), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True)), sa.Column('finished_at', sa.DateTime(timezone=True)))
    op.create_table('topics',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('fingerprint', sa.String(64), unique=True, nullable=False),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('analysis_jobs.id'), nullable=False),
        sa.Column('is_demo', sa.Boolean, nullable=False), sa.Column('engine', sa.String(20), nullable=False),
        sa.Column('title', sa.Text, nullable=False), sa.Column('question', sa.Text, nullable=False),
        sa.Column('category', sa.String(60), nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('favorite', sa.Boolean, nullable=False), sa.Column('research_locked', sa.Boolean, nullable=False), sa.Column('note', sa.Text), sa.Column('merged_into', sa.String(36)),
        sa.Column('evidence', sa.JSON, nullable=False), sa.Column('support_count', sa.Integer, nullable=False),
        sa.Column('coverage', sa.JSON, nullable=False), sa.Column('uncertainty', sa.Text, nullable=False),
        sa.Column('gap', sa.Text, nullable=False), sa.Column('score', sa.Float, nullable=False),
        sa.Column('scores', sa.JSON, nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('topic_decisions', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('topic_id', sa.String(36), sa.ForeignKey('topics.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(30), nullable=False), sa.Column('detail', sa.JSON, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('usage_ledger', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('job_id', sa.String(36), unique=True, nullable=False), sa.Column('budget_day', sa.String(10), nullable=False),
        sa.Column('reserved_cost', sa.Float, nullable=False), sa.Column('estimated_cost', sa.Float),
        sa.Column('charge_state', sa.String(30), nullable=False), sa.Column('usage', sa.JSON, nullable=False))
    op.create_index('ix_usage_ledger_budget_day', 'usage_ledger', ['budget_day'])

def downgrade():
    for table in ('usage_ledger', 'topic_decisions', 'topics', 'analysis_jobs'):
        op.drop_table(table)
