import os
import click
from flask.cli import with_appcontext
from sqlalchemy import text
from app import db
from app.models import User, AlocacaoCorretora
from werkzeug.security import generate_password_hash
from app.services.fatura_service import auto_gerar_ciclos_em_lote  # ALTERAÇÃO FASE 2

def register_cli_commands(app):
    
    @app.cli.command('setup-dw')
    @with_appcontext
    def setup_db():
        """Comando de segurança: Cria as tabelas e os 4 diretores da DW Capital."""
        click.echo("Iniciando setup corporativo da DW Capital...")
        db.create_all()
        
        # 🛡️ PROTEÇÃO FASE 1: Lendo a senha segura do ambiente (.env ou Render)
        senha_padrao = os.getenv('ADMIN_DEFAULT_PASSWORD')
        if not senha_padrao:
            click.echo("⚠️ ERRO CRÍTICO: A variável ADMIN_DEFAULT_PASSWORD não está configurada no ambiente!")
            click.echo("Abortando a criação dos usuários para manter a segurança do banco de dados.")
            return
        
        admin_antigo = User.query.filter_by(username='dwcapital').first()
        if admin_antigo:
            admin_antigo.status_acesso = 'inativo'
            admin_antigo.username = 'dwcapital_inativo' 
            
        novos_admins = [
            {'username': 'dwigor', 'nome': 'Igor Mikael'},
            {'username': 'dwwilliam', 'nome': 'William'},
            {'username': 'dwthaynara', 'nome': 'Thaynara'},
            {'username': 'dwdema', 'nome': 'Dermevaldo'}
        ]
        
        criados = 0
        for admin_data in novos_admins:
            existe = User.query.filter_by(username=admin_data['username']).first()
            if not existe:
                novo_admin = User(
                    username=admin_data['username'],
                    nome=admin_data['nome'],
                    password_hash=generate_password_hash(senha_padrao),
                    role='admin',
                    status_acesso='ativo',
                    precisa_trocar_senha=True 
                )
                db.session.add(novo_admin)
                criados += 1
                
        db.session.commit()
        click.echo(f"✅ Setup Concluído! {criados} novos acessos administrativos gerados com sucesso.")

    @app.cli.command('migrar-corretoras')
    @with_appcontext
    def migrar_corretoras():
        """Migra faturas do formato antigo para o novo formato Multi-Corretoras."""
        click.echo("Iniciando migração segura do banco...")
        try:
            db.session.execute(text('ALTER TABLE fatura_diaria ADD COLUMN IF NOT EXISTS nome_corretora VARCHAR(50);'))
            db.session.commit()
            click.echo("✅ Coluna verificada/criada.")
        except Exception as e_sql:
            db.session.rollback()
            click.echo(f"Aviso sobre a coluna (pode já existir): {str(e_sql)}")

        usuarios = User.query.all()
        alocacoes_criadas = 0
        faturas_corrigidas = 0
        
        for user in usuarios:
            if not user.corretora:
                continue
                
            existe = AlocacaoCorretora.query.filter_by(user_id=user.id, nome_corretora=user.corretora).first()
            if not existe:
                nova_alocacao = AlocacaoCorretora(
                    user_id=user.id,
                    nome_corretora=user.corretora.upper(),
                    capital_alocado=user.capital_alocado or 0.0
                )
                db.session.add(nova_alocacao)
                alocacoes_criadas += 1

            for fatura in user.faturas:
                for dia in fatura.dias:
                    if dia.nome_corretora is None or dia.nome_corretora.strip() == '':
                        dia.nome_corretora = user.corretora.upper()
                        faturas_corrigidas += 1
        
        db.session.commit()
        click.echo(f"✅ MIGRAÇÃO CONCLUÍDA! {alocacoes_criadas} alocações geradas e {faturas_corrigidas} dias corrigidos.")

    # ALTERAÇÃO FASE 2 - Comando para gerar ciclos em lote via cron
    @app.cli.command('gerar-ciclos')
    @with_appcontext
    def gerar_ciclos():
        """Gera automaticamente os ciclos semanais para todos os clientes ativos (deve ser executado via cron)."""
        click.echo("Iniciando geração de ciclos em lote...")
        clientes_ativos = User.query.filter_by(role='cliente', status_acesso='ativo').all()
        if not clientes_ativos:
            click.echo("Nenhum cliente ativo encontrado.")
            return
        auto_gerar_ciclos_em_lote(clientes_ativos)
        click.echo(f"✅ Ciclos processados para {len(clientes_ativos)} clientes ativos.")
