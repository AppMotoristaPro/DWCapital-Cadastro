import random
import string
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import User, AlocacaoCorretora, DocumentoTemplate, DocumentoCliente, ContaMT5Cliente
from app import db, limiter
from app.utils.validators import validar_cpf
from app.services.parcela_service import gerar_parcelas_compra_unificado
from app.services.conta_mt5_service import adicionar_conta
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def gerar_matricula_unica():
    while True:
        mat = ''.join(random.choices(string.digits, k=4))
        if not User.query.filter_by(matricula=mat).first():
            return mat

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
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
                session.permanent = True
                
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

# ==================== PROGRAMA DE INDICAÇÃO ====================

@auth_bp.route('/indicacao', methods=['GET', 'POST'])
def indicacao():
    ref = request.args.get('ref')
    if not ref or not ref.isdigit():
        flash('Link de indicação inválido.', 'error')
        return redirect(url_for('auth.login'))
    
    indicador = User.query.get(int(ref))
    if not indicador or indicador.role != 'cliente' or indicador.status_acesso != 'ativo':
        flash('Link de indicação inválido.', 'error')
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
        modelo = request.form.get('modelo')
        
        if not validar_cpf(cpf):
            flash('CPF inválido. Verifique os dígitos.', 'error')
            return render_template('auth/indicacao.html', indicador=indicador)
        
        if modelo not in ['comissao', 'compra']:
            flash('Selecione um modelo válido.', 'error')
            return render_template('auth/indicacao.html', indicador=indicador)
        
        # Verifica se CPF já existe
        user_existente = User.query.filter_by(cpf=cpf).first()
        if user_existente:
            flash('Este CPF já está cadastrado. Faça login.', 'error')
            return redirect(url_for('auth.login'))
        
        # Cria usuário pendente
        novo_user = User(
            cpf=cpf,
            role='cliente',
            status_acesso='pendente_cadastro',
            modelo_negocio=modelo,
            indicador_id=indicador.id,
            is_indicado=(modelo == 'compra'),
            data_indicacao=datetime.now(tz_br) if modelo == 'compra' else None
        )
        db.session.add(novo_user)
        db.session.commit()
        
        # Armazena na sessão para o próximo passo
        session['cpf_cadastro'] = cpf
        session['modelo_cadastro'] = modelo
        
        flash('CPF validado! Complete seu cadastro abaixo.', 'success')
        return redirect(url_for('auth.primeiro_acesso'))
    
    # GET - exibe o formulário
    return render_template('auth/indicacao.html', indicador=indicador)

# ==================== PRIMEIRO ACESSO MODIFICADO ====================

@auth_bp.route('/primeiro_acesso', methods=['GET', 'POST'])
def primeiro_acesso():
    cpf_sessao = session.get('cpf_cadastro')
    modelo_sessao = session.get('modelo_cadastro')
    
    if request.method == 'GET':
        if cpf_sessao and modelo_sessao:
            user = User.query.filter_by(cpf=cpf_sessao, status_acesso='pendente_cadastro').first()
            if user:
                return render_template('auth/primeiro_acesso.html', 
                                       cpf_preenchido=cpf_sessao,
                                       modelo_pre_selecionado=modelo_sessao)
        return render_template('auth/primeiro_acesso.html', cpf_preenchido=None, modelo_pre_selecionado=None)
    
    # POST - processa o cadastro
    cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
    
    # Se veio de indicação, usa o CPF da sessão (mais seguro)
    if cpf_sessao:
        cpf = cpf_sessao
    else:
        # Validação normal para cadastro manual (sem indicação)
        if not validar_cpf(cpf):
            flash('CPF inválido. Verifique os dígitos e tente novamente.', 'error')
            return render_template('auth/primeiro_acesso.html')
    
    user = User.query.filter_by(cpf=cpf, status_acesso='pendente_cadastro').first()
    
    if not user:
        # Se não existir, pode ser tentativa de cadastro manual sem liberação prévia (bloqueado)
        flash('CPF não liberado. Entre em contato com o suporte.', 'error')
        return render_template('auth/primeiro_acesso.html')
    
    # Se veio de indicação, o modelo_negocio já está definido; caso contrário, usa o do formulário
    if not user.modelo_negocio:
        user.modelo_negocio = request.form.get('modelo_negocio', 'comissao')
    
    # Valida capital mínimo e processa dados do formulário
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

    # ==================== NOVO: Criação da conta MT5 e parcelas (se compra) ====================
    if user.modelo_negocio == 'compra':
        conta_mt5_numero = request.form.get('conta_mt5', '').strip()
        if not conta_mt5_numero:
            flash('Número da conta MT5 é obrigatório para o modelo compra.', 'error')
            return render_template('auth/primeiro_acesso.html', 
                                   cpf_preenchido=cpf_sessao, 
                                   modelo_pre_selecionado=user.modelo_negocio)
        
        # Corretora associada à conta MT5 (escolhida pelo cliente)
        corretora_conta = request.form.get('conta_corretora')
        if not corretora_conta:
            # Fallback: usa a primeira corretora da lista
            corretora_conta = corretoras_selecionadas[0] if corretoras_selecionadas else 'GENIAL'
        
        try:
            # Cria a conta MT5 com os dados informados
            nova_conta = adicionar_conta(
                user_id=user.id,
                numero_conta=conta_mt5_numero,
                nome_corretora=corretora_conta,
                capital_alocado=soma_capital  # ou pode ser 0, conforme sua regra
            )
            # Gera as 10 parcelas associadas a essa conta
            hoje = datetime.now(tz_br).date()
            parcelas = gerar_parcelas_compra_unificado(user.id, nova_conta.id, data_inicio=hoje)
            db.session.add_all(parcelas)
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar conta MT5: {str(e)}', 'error')
            return render_template('auth/primeiro_acesso.html',
                                   cpf_preenchido=cpf_sessao,
                                   modelo_pre_selecionado=user.modelo_negocio)
    
    # ==================== Criação de documentos de onboarding ====================
    templates_onboarding = DocumentoTemplate.query.filter_by(is_onboarding=True).all()
    if templates_onboarding:
        existing = DocumentoCliente.query.filter_by(user_id=user.id).first()
        if not existing:
            docs_onboarding = [
                DocumentoCliente(
                    user_id=user.id,
                    template_id=t.id,
                    status='na_fila'
                ) for t in templates_onboarding
            ]
            db.session.add_all(docs_onboarding)
    # ==================================================================================
    
    # Limpa a sessão (se veio de indicação)
    session.pop('cpf_cadastro', None)
    session.pop('modelo_cadastro', None)
    
    db.session.commit()
    flash('Cadastro concluído com sucesso! Bem-vindo à DW Capital.', 'auth_success')
    return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))