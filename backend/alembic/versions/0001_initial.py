"""Initial persistent import library."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None

def upgrade():
    op.create_table('import_jobs', sa.Column('id', sa.String(36), primary_key=True), sa.Column('digest', sa.String(64), unique=True, nullable=False), sa.Column('adapter', sa.String(40), nullable=False), sa.Column('is_demo', sa.Boolean, nullable=False), sa.Column('raw_data', sa.JSON, nullable=False), sa.Column('status', sa.String(20), nullable=False), sa.Column('result', sa.JSON, nullable=False), sa.Column('error', sa.Text), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('videos', sa.Column('id', sa.String(36), primary_key=True), sa.Column('platform', sa.String(40), nullable=False), sa.Column('external_id', sa.String(200), nullable=False), sa.Column('title', sa.Text, nullable=False), sa.Column('content', sa.Text), sa.Column('source_url', sa.Text, nullable=False), sa.Column('published_at', sa.DateTime(timezone=True)), sa.Column('collected_at', sa.DateTime(timezone=True), nullable=False), sa.Column('is_demo', sa.Boolean, nullable=False), sa.Column('tags', sa.JSON, nullable=False), sa.Column('related_searches', sa.JSON, nullable=False), sa.UniqueConstraint('platform', 'external_id', 'is_demo'))
    op.create_table('comments', sa.Column('id', sa.String(36), primary_key=True), sa.Column('video_id', sa.String(36), sa.ForeignKey('videos.id', ondelete='CASCADE'), nullable=False), sa.Column('external_id', sa.String(200), nullable=False), sa.Column('text', sa.Text, nullable=False), sa.Column('likes', sa.Integer), sa.UniqueConstraint('video_id', 'external_id'))
    op.create_table('metric_snapshots', sa.Column('id', sa.String(36), primary_key=True), sa.Column('video_id', sa.String(36), sa.ForeignKey('videos.id', ondelete='CASCADE'), nullable=False), sa.Column('import_id', sa.String(36), sa.ForeignKey('import_jobs.id'), nullable=False), sa.Column('collected_at', sa.DateTime(timezone=True), nullable=False), sa.Column('metrics', sa.JSON, nullable=False))

def downgrade():
    for table in ('metric_snapshots', 'comments', 'videos', 'import_jobs'):
        op.drop_table(table)
