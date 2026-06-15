# app/services/conta_mt5_service.py
"""
Serviço para gerenciar as contas MT5 dos clientes.
Permite adicionar, editar, desativar, listar e verificar contas.
"""
from app import db
from app.models import ContaMT5Cliente
from datetime import datetime
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')


def listar_contas(user_id, apenas_ativas=True):
    """Retorna todas as contas de um usuário, opcionalmente apenas ativas."""
    query = ContaMT5Cliente.query.filter_by(user_id=user_id)
    if apenas_ativas:
        query = query.filter_by(ativo=True)
    return query.order_by(ContaMT5Cliente.data_cadastro.desc()).all()


def obter_conta(conta_id, user_id):
    """Obtém uma conta específica do usuário, verificando permissão."""
    return ContaMT5Cliente.query.filter_by(id=conta_id, user_id=user_id).first()


def adicionar_conta(user_id, numero_conta, nome_corretora, capital_alocado=0.0):
    """
    Adiciona uma nova conta MT5 para o usuário.
    Valida se o número da conta não está duplicado para o mesmo usuário (ativo).
    """
    # Verifica se já existe uma conta ativa com o mesmo número
    existente = ContaMT5Cliente.query.filter_by(
        user_id=user_id,
        numero_conta=numero_conta,
        ativo=True
    ).first()
    if existente:
        raise ValueError("Já existe uma conta ativa com este número para este cliente.")

    nova = ContaMT5Cliente(
        user_id=user_id,
        numero_conta=numero_conta,
        nome_corretora=nome_corretora.upper(),
        capital_alocado=capital_alocado,
        ativo=True,
        bloqueada=False,
        data_cadastro=datetime.now(tz_br)
    )
    db.session.add(nova)
    db.session.commit()
    return nova


def atualizar_conta(conta_id, user_id, **kwargs):
    """
    Atualiza os campos de uma conta (capital_alocado, nome_corretora, etc.).
    Não permite atualizar número da conta (evita inconsistências).
    """
    conta = obter_conta(conta_id, user_id)
    if not conta:
        raise ValueError("Conta não encontrada.")

    campos_permitidos = ['capital_alocado', 'nome_corretora']
    for campo in campos_permitidos:
        if campo in kwargs:
            setattr(conta, campo, kwargs[campo])
    if 'nome_corretora' in kwargs:
        conta.nome_corretora = kwargs['nome_corretora'].upper()

    db.session.commit()
    return conta


def desativar_conta(conta_id, user_id):
    """Desativa a conta (não exclui, para manter histórico)."""
    conta = obter_conta(conta_id, user_id)
    if not conta:
        raise ValueError("Conta não encontrada.")
    conta.ativo = False
    db.session.commit()
    return conta


def bloquear_conta(conta_id, user_id, bloqueado):
    """
    Altera o status de bloqueio da conta (admin apenas).
    Se bloqueada, o cliente não pode baixar/gerar licença para esta conta.
    """
    conta = obter_conta(conta_id, user_id)
    if not conta:
        raise ValueError("Conta não encontrada.")
    conta.bloqueada = bloqueado
    db.session.commit()
    return conta


def contar_contas_ativas(user_id):
    """Retorna o número de contas ativas do usuário."""
    return ContaMT5Cliente.query.filter_by(user_id=user_id, ativo=True).count()


def obter_conta_padrao(user_id):
    """Retorna a primeira conta ativa do usuário (para fallback)."""
    return ContaMT5Cliente.query.filter_by(user_id=user_id, ativo=True).order_by(ContaMT5Cliente.id).first()


def validar_numero_conta(numero):
    """Validação simples: apenas números e entre 1 e 20 caracteres."""
    return numero.isdigit() and 1 <= len(numero) <= 20