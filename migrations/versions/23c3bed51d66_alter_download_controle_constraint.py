"""alter_download_controle_constraint

Revision ID: 23c3bed51d66
Revises: efdbf520c638
Create Date: 2026-06-12 15:19:02.605055

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '23c3bed51d66'
down_revision = 'efdbf520c638'
branch_labels = None
depends_on = None

def upgrade():
    # Remove a constraint antiga (user_id, versao_id)
    op.execute('ALTER TABLE download_controle DROP CONSTRAINT IF EXISTS _user_versao_uc')
    # Adiciona a nova constraint incluindo ciclo_inicio
    op.execute('ALTER TABLE download_controle ADD CONSTRAINT _user_versao_ciclo_uc UNIQUE (user_id, versao_id, ciclo_inicio)')

def downgrade():
    # Remove a nova constraint
    op.execute('ALTER TABLE download_controle DROP CONSTRAINT IF EXISTS _user_versao_ciclo_uc')
    # Recria a constraint antiga
    op.execute('ALTER TABLE download_controle ADD CONSTRAINT _user_versao_uc UNIQUE (user_id, versao_id)')