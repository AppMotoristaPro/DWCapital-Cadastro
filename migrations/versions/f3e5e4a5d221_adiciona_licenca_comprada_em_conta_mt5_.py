"""adiciona licenca_comprada em conta_mt5_cliente

Revision ID: f3e5e4a5d221
Revises: 084437191764
Create Date: 2026-06-16 14:00:33.484175

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3e5e4a5d221'
down_revision = '084437191764'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Adicionar coluna licenca_comprada (default False)
    with op.batch_alter_table('conta_mt5_cliente') as batch_op:
        batch_op.add_column(sa.Column('licenca_comprada', sa.Boolean(), nullable=False, server_default='false'))

    # 2. Migrar dados para clientes comissão: todas as contas ativas recebem True
    op.execute("""
        UPDATE conta_mt5_cliente c
        SET licenca_comprada = true
        FROM "user" u
        WHERE c.user_id = u.id
          AND u.modelo_negocio = 'comissao'
          AND c.ativo = true
    """)

    # 3. Migrar dados para clientes compra: contas com parcelas ou licenças ativas recebem True
    op.execute("""
        UPDATE conta_mt5_cliente c
        SET licenca_comprada = true
        WHERE EXISTS (
            SELECT 1 FROM parcela_compra p
            WHERE p.conta_mt5_id = c.id
        )
        OR EXISTS (
            SELECT 1 FROM licenca_cliente l
            WHERE l.conta_mt5_id = c.id
              AND l.status = 'ativa'
        )
    """)


def downgrade():
    with op.batch_alter_table('conta_mt5_cliente') as batch_op:
        batch_op.drop_column('licenca_comprada')
