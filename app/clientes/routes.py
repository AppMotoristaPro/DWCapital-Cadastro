from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required
from app import db
from app.models import Cliente

clientes_bp = Blueprint('clientes', __name__, url_prefix='/clientes')

@clientes_bp.route('/')
@login_required
def index():
    # Lista todos os clientes em ordem de cadastro (mais recentes primeiro)
    clientes = Cliente.query.order_by(Cliente.id.desc()).all()
    return render_template('clientes/index.html', clientes=clientes)

@clientes_bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        novo_cliente = Cliente(
            nome=request.form.get('nome'),
            email=request.form.get('email'),
            celular=request.form.get('celular'),
            valor_alocado=float(request.form.get('valor_alocado') or 0.0),
            corretora=request.form.get('corretora')
        )
        db.session.add(novo_cliente)
        db.session.commit()
        flash('Cliente cadastrado com sucesso!', 'success')
        return redirect(url_for('clientes.index'))
        
    return render_template('clientes/form.html', cliente=None)

@clientes_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    cliente = Cliente.query.get_or_404(id)
    
    if request.method == 'POST':
        cliente.nome = request.form.get('nome')
        cliente.email = request.form.get('email')
        cliente.celular = request.form.get('celular')
        cliente.valor_alocado = float(request.form.get('valor_alocado') or 0.0)
        cliente.corretora = request.form.get('corretora')
        
        db.session.commit()
        flash('Dados do cliente atualizados!', 'success')
        return redirect(url_for('clientes.index'))
        
    return render_template('clientes/form.html', cliente=cliente)

@clientes_bp.route('/status/<int:id>', methods=['POST'])
@login_required
def toggle_status(id):
    cliente = Cliente.query.get_or_404(id)
    # Inverte o status
    cliente.status = 'inativo' if cliente.status == 'ativo' else 'ativo'
    db.session.commit()
    flash(f'Status de {cliente.nome} alterado para {cliente.status.upper()}.', 'success')
    return redirect(url_for('clientes.index'))

@clientes_bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
def excluir(id):
    cliente = Cliente.query.get_or_404(id)
    nome = cliente.nome
    db.session.delete(cliente)
    db.session.commit()
    flash(f'Cliente {nome} e todo o seu histórico foram excluídos.', 'success')
    return redirect(url_for('clientes.index'))

