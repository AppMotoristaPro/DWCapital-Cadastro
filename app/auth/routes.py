import random
import string
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text 
from app.models import User, AlocacaoCorretora, FaturaDiaria
from app import db

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def gerar_matricula_unica():
    while True:
        mat = ''.join(random.choices(string.digits, k=4))
        if not User.query.filter_by(matricula=mat).first():
            return mat

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if getattr(current_user, 'precisa_trocar_senha', False):
            return redirect(url_for('auth.forcar_troca_senha'))
        return redirect(url_for('admin.dashboard' if current_user.role == 'admin' else 'client.dashboard'))

    if request.method == 'POST':
        identificador = request.form.get('login')
        senha = request.form.get('senha')
        
        user = User.query.filter((User.cpf == identificador) | (User.username == identificador)).first()

        if user and check_password_hash(user.password_hash, senha):
            if user.status_acesso == 'ativo':
                login_user(user)
                if getattr(user, 'precisa_trocar_senha', False):
                    return redirect(url_for('auth.forcar_troca_senha'))
                    
                return redirect(url_for('admin.dashboard' if user.role == 'admin' else 'client.dashboard'))
            flash('Cadastro pendente. Vá em Primeiro Acesso.', 'auth_error')
        else:
            flash('Credenciais inválidas.', 'auth_error')
            
    return render_template('auth/login.html')

@auth_bp.route('/forcar_troca_senha', methods=['GET', 'POST'])
@login_required
def forcar_troca_senha():
    if not current_user.precisa_trocar_senha:
        return redirect(url_for('admin.dashboard' if current_user.role == 'admin' else 'client.dashboard'))
        
    if request.method == 'POST':
        nova_senha = request.form.get('senha')
        current_user.password_hash = generate_password_hash(nova_senha)
        current_user.precisa_trocar_senha = False
        db.session.commit()
        
        flash('Sua senha foi atualizada com sucesso!', 'success')
        return redirect(url_for('admin.dashboard' if current_user.role == 'admin' else 'client.dashboard'))
        
    return render_template('auth/trocar_senha.html')

@auth_bp.route('/api/verificar_cpf', methods=['POST'])
def verificar_cpf():
    data = request.get_json()
    if not data or 'cpf' not in data:
        return jsonify({'valido': False, 'mensagem': 'CPF não informado.'}), 400

    cpf_limpo = ''.join(filter(str.isdigit, data['cpf']))
    user = User.query.filter_by(cpf=cpf_limpo).first()

    if not user:
        return jsonify({'valido': False, 'mensagem': 'CPF não liberado. Entre em contato com a DW Capital.'})
    
    if user.status_acesso != 'pendente_cadastro':
        return jsonify({'valido': False, 'mensagem': 'Este CPF já possui uma senha ativa.'})

    return jsonify({'valido': True, 'mensagem': 'CPF liberado!'})

@auth_bp.route('/primeiro_acesso', methods=['GET', 'POST'])
def primeiro_acesso():
    if request.method == 'POST':
        cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
        user = User.query.filter_by(cpf=cpf, status_acesso='pendente_cadastro').first()

        if user:
            corretoras_selecionadas = request.form.getlist('corretora[]')
            capitais_alocados = request.form.getlist('capital[]')
            
            # VALIDAÇÃO DE SEGURANÇA (Backend): Bloqueia capital < R$ 10.000,00
            for cap in capitais_alocados:
                if cap and float(cap) < 10000:
                    flash('Operação cancelada: O capital mínimo exigido por corretora é de R$ 10.000,00.', 'error')
                    return render_template('auth/primeiro_acesso.html')

            # FORMATAÇÃO DE NOME (Capitalize global)
            nome_raw = request.form.get('nome', '')
            user.nome = nome_raw.strip().title()
            
            user.email = request.form.get('email')
            user.celular = request.form.get('celular')
            
            rua = request.form.get('rua', '')
            numero = request.form.get('numero', '')
            bairro = request.form.get('bairro', '')
            cidade = request.form.get('cidade', '')
            estado = request.form.get('estado', '')
            cep = request.form.get('cep', '')
            
            user.endereco = f"{rua}, {numero} - {bairro}, {cidade}/{estado} - CEP: {cep}"
            user.password_hash = generate_password_hash(request.form.get('senha'))
            user.matricula = gerar_matricula_unica() 
            user.status_acesso = 'ativo'
            
            AlocacaoCorretora.query.filter_by(user_id=user.id).delete()
            
            for corretora, capital in zip(corretoras_selecionadas, capitais_alocados):
                if corretora and capital:
                    nova_alocacao = AlocacaoCorretora(
                        user_id=user.id,
                        nome_corretora=corretora.upper(),
                        capital_alocado=float(capital)
                    )
                    db.session.add(nova_alocacao)
            
            db.session.commit()
            flash('Cadastro concluído com sucesso! Bem-vindo à DW Capital.', 'auth_success')
            return redirect(url_for('auth.login'))
        
        flash('CPF não liberado ou cadastro já ativo.', 'error')

    return render_template('auth/primeiro_acesso.html')

@auth_bp.route('/setup_secreto_dw')
def setup_secreto():
    try:
        db.create_all()
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
                    password_hash=generate_password_hash('dwtemp2026'),
                    role='admin',
                    status_acesso='ativo',
                    precisa_trocar_senha=True 
                )
                db.session.add(novo_admin)
                criados += 1
                
        db.session.commit()
        return f"✅ Setup Corporativo Concluído! {criados} novos acessos administrativos foram gerados com sucesso."
    except Exception as e:
        db.session.rollback()
        return f"❌ Erro no setup: {e}"

@auth_bp.route('/migracao_secreta_dw')
def migracao_secreta():
    try:
        try:
            db.session.execute(text('ALTER TABLE fatura_diaria ADD COLUMN IF NOT EXISTS nome_corretora VARCHAR(50);'))
            db.session.commit()
            msg_coluna = "Coluna 'nome_corretora' forçada com sucesso! "
        except Exception as e_sql:
            db.session.rollback()
            msg_coluna = f"Aviso sobre a coluna (pode já existir): {str(e_sql)}. "

        usuarios = User.query.all()
        alocacoes_criadas = 0
        faturas_corrigidas = 0
        
        for user in usuarios:
            if not user.corretora:
                continue
                
            existe = AlocacaoCorretora.query.filter_by(
                user_id=user.id, 
                nome_corretora=user.corretora
            ).first()
            
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
        return f"✅ {msg_coluna} MIGRAÇÃO CONCLUÍDA! {alocacoes_criadas} alocações convertidas e {faturas_corrigidas} dias corrigidos com sucesso. O histórico dos clientes está a salvo."
        
    except Exception as e:
        db.session.rollback()
        return f"❌ Erro ao salvar migração: {str(e)}"

@auth_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

