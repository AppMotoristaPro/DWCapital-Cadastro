import os
import random
import string
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from app.models import User, Fatura, FaturaDiaria
from app import db
from datetime import datetime, timedelta
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/')
@login_required
def dashboard():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    filtro_mes = request.args.get('mes')
    faturas_base = Fatura.query.filter(Fatura.status.in_(['parcial', 'relatorio_enviado', 'pago', 'inadimplente']))
    
    if filtro_mes:
        dt_inicio = datetime.strptime(filtro_mes + '-01', '%Y-%m-%d').date()
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio).all()
    else:
        faturas_filtradas = faturas_base.all()
        
    faturamento_total = sum(f.repasse for f in faturas_filtradas)
    clientes_ativos = User.query.filter_by(role='cliente', status_acesso='ativo').count()
    
    return render_template('admin/dashboard.html', 
                           clientes_ativos=clientes_ativos,
                           faturamento_total=faturamento_total)

@admin_bp.route('/clientes')
@login_required
def clientes_list():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    busca = request.args.get('q', '')
    query = User.query.filter_by(role='cliente')
    if busca:
        query = query.filter((User.nome.ilike(f'%{busca}%')) | (User.matricula.ilike(f'%{busca}%')))
    clientes = query.order_by(User.id.desc()).all()
    return render_template('admin/index.html', clientes=clientes, busca=busca)

@admin_bp.route('/liberar_cliente', methods=['POST'])
@login_required
def liberar_cliente():
    cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
    nome_temp = request.form.get('nome_temp')
    
    if User.query.filter_by(cpf=cpf).first():
        flash('CPF já cadastrado.', 'error')
        return redirect(url_for('admin.clientes_list'))

    novo = User(cpf=cpf, nome=nome_temp, role='cliente', status_acesso='pendente_cadastro')
    db.session.add(novo)
    db.session.flush()
    
    # Gera ciclo inicial
    hoje = datetime.now().date()
    inicio_ciclo = hoje - timedelta(days=hoje.weekday())
    fatura = Fatura(user_id=novo.id, data_inicio=inicio_ciclo, data_fim=inicio_ciclo + timedelta(days=6))
    db.session.add(fatura)
    
    for i in range(5): # Seg a Sex
        fd = FaturaDiaria(fatura_id=fatura.id, data_pregao=inicio_ciclo + timedelta(days=i))
        db.session.add(fd)

    db.session.commit()
    flash('Acesso liberado!', 'success')
    return redirect(url_for('admin.clientes_list'))

@admin_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    cliente = User.query.get_or_404(id)
    if request.method == 'POST':
        cliente.nome = request.form.get('nome')
        cliente.capital_alocado = float(request.form.get('capital') or 0.0)
        db.session.commit()
        flash('Atualizado!', 'success')
        return redirect(url_for('admin.clientes_list'))
    return render_template('admin/editar.html', cliente=cliente)

@admin_bp.route('/pagamentos')
@login_required
def pagamentos():
    ativos = User.query.filter_by(role='cliente', status_acesso='ativo').all()
    return render_template('admin/pagamentos.html', clientes=ativos)

@admin_bp.route('/pagamentos/<int:id>')
@login_required
def pagamentos_cliente(id):
    cliente = User.query.get_or_404(id)
    faturas = Fatura.query.filter_by(user_id=cliente.id).order_by(Fatura.data_inicio.desc()).all()
    return render_template('admin/pagamentos_cliente.html', cliente=cliente, faturas=faturas)

@admin_bp.route('/pagamentos/status/<int:fatura_id>', methods=['POST'])
@login_required
def status_pagamento(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    fatura.status = request.form.get('status')
    db.session.commit()
    return redirect(url_for('admin.pagamentos_cliente', id=fatura.user_id))

@admin_bp.route('/pagamentos/rejeitar/<int:dia_id>', methods=['POST'])
@login_required
def rejeitar_relatorio(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    dia.arquivo_pdf, dia.status = None, 'pendente'
    db.session.commit()
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id))

@admin_bp.route('/gerar_senha_temporaria/<int:id>', methods=['POST'])
@login_required
def gerar_senha_temporaria(id):
    cliente = User.query.get_or_404(id)
    senha_temp = "DW@" + ''.join(random.choices(string.ascii_letters + string.digits, k=5))
    cliente.password_hash = generate_password_hash(senha_temp)
    cliente.precisa_trocar_senha = True
    db.session.commit()
    flash(f'Senha temporária para {cliente.nome}: {senha_temp}', 'success')
    return redirect(url_for('admin.editar_cliente', id=cliente.id))

