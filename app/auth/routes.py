import random
import string
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import User, AlocacaoCorretora
from app import db, limiter

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def gerar_matricula_unica():
    while True:
        mat = ''.join(random.choices(string.digits, k=4))
        if not User.query.filter_by(matricula=mat).first():
            return mat

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"]) # <-- CORREÇÃO: Limita apenas envios de form, não recarregamentos
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
                
                # ==========================================
                # ATIVANDO A TRAVA DE VALIDADE DO LOGIN
                # ==========================================
                session.permanent = True
                # ==========================================
                
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
@limiter.limit("5 per minute")
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
            
            for cap in capitais_alocados:
                if cap and float(cap) < 10000:
                    flash('Operação cancelada: O capital mínimo exigido por corretora é de R$ 10.000,00.', 'error')
                    return render_template('auth/primeiro_acesso.html')

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
            
            soma_capital = 0.0 
            
            for corretora, capital in zip(corretoras_selecionadas, capitais_alocados):
                if corretora and capital:
                    valor_capital = float(capital)
                    nova_alocacao = AlocacaoCorretora(
                        user_id=user.id,
                        nome_corretora=corretora.upper(),
                        capital_alocado=valor_capital
                    )
                    db.session.add(nova_alocacao)
                    soma_capital += valor_capital 
            
            user.capital_alocado = soma_capital 
            
            db.session.commit()
            flash('Cadastro concluído com sucesso! Bem-vindo à DW Capital.', 'auth_success')
            return redirect(url_for('auth.login'))
        
        flash('CPF não liberado ou cadastro já ativo.', 'error')

    return render_template('auth/primeiro_acesso.html')

@auth_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))