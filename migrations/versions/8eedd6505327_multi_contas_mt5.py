"""multi_contas_mt5

Revision ID: 8eedd6505327
Revises: 2c445905d6a4
Create Date: 2026-06-15 11:32:57.529996

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '8eedd6505327'
down_revision = '2c445905d6a4'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Criar a tabela conta_mt5_cliente
    op.create_table('conta_mt5_cliente',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('numero_conta', sa.String(length=20), nullable=False),
        sa.Column('nome_corretora', sa.String(length=50), nullable=False),
        sa.Column('capital_alocado', sa.Float(), nullable=True),
        sa.Column('ativo', sa.Boolean(), nullable=True),
        sa.Column('bloqueada', sa.Boolean(), nullable=True),
        sa.Column('data_cadastro', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 2. Migrar contas existentes (usuários com conta_mt5 preenchida)
    op.execute("""
        INSERT INTO conta_mt5_cliente (user_id, numero_conta, nome_corretora, capital_alocado, ativo, bloqueada, data_cadastro)
        SELECT 
            u.id,
            u.conta_mt5,
            COALESCE(u.corretora, 'GENIAL'),
            COALESCE(u.capital_alocado, 0.0),
            true,
            false,
            NOW()
        FROM "user" u
        WHERE u.conta_mt5 IS NOT NULL AND u.conta_mt5 != ''
    """)

    # 3. Criar conta padrão para TODOS os usuários que ainda não têm conta
    #    Isso garante que nenhum cliente fique sem conta (evita NULL posterior)
    op.execute("""
        INSERT INTO conta_mt5_cliente (user_id, numero_conta, nome_corretora, capital_alocado, ativo, bloqueada, data_cadastro)
        SELECT 
            u.id,
            'PENDENTE',                         -- número padrão
            COALESCE(u.corretora, 'GENIAL'),
            COALESCE(u.capital_alocado, 0.0),
            true,
            false,
            NOW()
        FROM "user" u
        WHERE u.id NOT IN (SELECT user_id FROM conta_mt5_cliente)
    """)

    # 4. Adicionar coluna conta_mt5_id em download_controle (nullable inicialmente)
    with op.batch_alter_table('download_controle', schema=None) as batch_op:
        batch_op.add_column(sa.Column('conta_mt5_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_download_conta', 'conta_mt5_cliente', ['conta_mt5_id'], ['id'])

    # 5. Associar downloads existentes à conta do respectivo usuário (a primeira criada)
    op.execute("""
        UPDATE download_controle dc
        SET conta_mt5_id = (
            SELECT id FROM conta_mt5_cliente c 
            WHERE c.user_id = dc.user_id 
            ORDER BY c.id LIMIT 1
        )
        WHERE conta_mt5_id IS NULL
    """)

    # 6. Tornar a coluna NOT NULL e ajustar constraints
    with op.batch_alter_table('download_controle', schema=None) as batch_op:
        batch_op.alter_column('conta_mt5_id', nullable=False)
        batch_op.drop_constraint(batch_op.f('_user_versao_uc'), type_='unique')
        batch_op.create_unique_constraint('_conta_versao_ciclo_uc', ['conta_mt5_id', 'versao_id', 'ciclo_inicio'])

    # 7. Adicionar coluna conta_mt5_id em licenca_cliente (nullable inicialmente)
    with op.batch_alter_table('licenca_cliente', schema=None) as batch_op:
        batch_op.add_column(sa.Column('conta_mt5_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_licenca_conta', 'conta_mt5_cliente', ['conta_mt5_id'], ['id'])

    # 8. Associar licenças existentes à conta do respectivo usuário
    op.execute("""
        UPDATE licenca_cliente lc
        SET conta_mt5_id = (
            SELECT id FROM conta_mt5_cliente c 
            WHERE c.user_id = lc.user_id 
            ORDER BY c.id LIMIT 1
        )
        WHERE conta_mt5_id IS NULL
    """)

    # 9. Tornar a coluna NOT NULL e ajustar constraints
    with op.batch_alter_table('licenca_cliente', schema=None) as batch_op:
        batch_op.alter_column('conta_mt5_id', nullable=False)
        batch_op.drop_constraint(batch_op.f('_user_ciclo_uc'), type_='unique')
        batch_op.create_unique_constraint('_conta_ciclo_uc', ['conta_mt5_id', 'ciclo_inicio'])
        batch_op.drop_column('conta_mt5')   # remove a coluna antiga

    # 10. Remover a coluna antiga user.conta_mt5
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('conta_mt5')


def downgrade():
    # 1. Restaurar a coluna user.conta_mt5
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('conta_mt5', sa.VARCHAR(length=20), nullable=True))

    # 2. Restaurar a coluna licenca_cliente.conta_mt5
    with op.batch_alter_table('licenca_cliente', schema=None) as batch_op:
        batch_op.add_column(sa.Column('conta_mt5', sa.VARCHAR(length=20), nullable=True))
        # Recuperar o número da conta a partir da tabela conta_mt5_cliente
        op.execute("""
            UPDATE licenca_cliente lc
            SET conta_mt5 = (
                SELECT c.numero_conta FROM conta_mt5_cliente c 
                WHERE c.id = lc.conta_mt5_id
            )
            WHERE lc.conta_mt5_id IS NOT NULL
        """)
        batch_op.drop_constraint('_conta_ciclo_uc', type_='unique')
        batch_op.create_unique_constraint(batch_op.f('_user_ciclo_uc'), ['user_id', 'ciclo_inicio'])
        batch_op.drop_constraint('fk_licenca_conta', type_='foreignkey')
        batch_op.drop_column('conta_mt5_id')

    # 3. Restaurar download_controle
    with op.batch_alter_table('download_controle', schema=None) as batch_op:
        batch_op.drop_constraint('_conta_versao_ciclo_uc', type_='unique')
        batch_op.create_unique_constraint(batch_op.f('_user_versao_uc'), ['user_id', 'versao_id'])
        batch_op.drop_constraint('fk_download_conta', type_='foreignkey')
        batch_op.drop_column('conta_mt5_id')

    # 4. Remover a tabela conta_mt5_cliente
    op.drop_table('conta_mt5_cliente')