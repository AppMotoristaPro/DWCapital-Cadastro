# migrations/versions/xxxx_remove_unique_contraint_licenca.py
from alembic import op

def upgrade():
    op.drop_constraint('_user_ciclo_uc', 'licenca_cliente', type_='unique')

def downgrade():
    op.create_unique_constraint('_user_ciclo_uc', 'licenca_cliente', ['user_id', 'ciclo_inicio'])
