# app/services/conta_mt5_service.py
"""
Serviço para gerenciar as contas MT5 dos clientes.
Permite adicionar, editar, desativar, listar e verificar contas.
Sincroniza automaticamente com AlocacaoCorretora para gerar faturas.
"""
from app import db
from app.models import ContaMT5Cliente, AlocacaoCorretora
from datetime import datetime
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')


def _sincronizar_alocacao(user_id, nome_corretora, capital_alocado):
    """
    Cria ou atualiza a AlocacaoCorretora correspondente à conta MT5.
    Se já existir uma alocação com o mesmo nome_corretora, atualiza o capital.
    Caso contrário, cria uma nova.
    """
    aloc = AlocacaoCorretora.query.filter_by(user_id=user_id, nome_corretora=nome_corretora).first()
    if aloc:
        aloc.capital_alocado = capital_alocado
    else:
        aloc = AlocacaoCorretora(
            user_id=user_id,
            nome_corretora=nome_corretora,
            capital_alocado=capital_alocado
        )
        db.session.add(aloc)
    db.session.commit()
    return aloc


def _remover_sincronizacao(user_id, nome_corretora):
    """Remove a AlocacaoCorretora correspondente (se existir)."""
    aloc = AlocacaoCorretora.query.filter_by(user_id=user_id, nome_corretora=nome_corretora).first()
    if aloc:
        db.session.delete(aloc)
        db.session.commit()


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
    Cria/atualiza a AlocacaoCorretora correspondente.
    """
    # A constraint UniqueConstraint('user_id', 'numero_conta') já impede duplicidade
    existente = ContaMT5Cliente.query.filter_by(
        user_id=user_id,
        numero_conta=numero_conta
    ).first()
    if existente:
        raise ValueError("Este número de conta MT5 já está cadastrado para este cliente.")

    nova = ContaMT5Cliente(
        user_id=user_id,
        numero_conta=numero_conta,
        nome_corretora=nome_corretora.upper(),
        capital_alocado=float(capital_alocado),
        ativo=True,
        bloqueada=False,
        data_cadastro=datetime.now(tz_br)
    )
    db.session.add(nova)
    db.session.commit()

    # Sincroniza com AlocacaoCorretora
    _sincronizar_alocacao(user_id, nome_corretora.upper(), float(capital_alocado))

    return nova


def atualizar_conta(conta_id, user_id, **kwargs):
    """Atualiza capital e corretora, e sincroniza a alocação."""
    conta = obter_conta(conta_id, user_id)
    if not conta:
        raise ValueError("Conta não encontrada.")

    if 'capital_alocado' in kwargs:
        try:
            kwargs['capital_alocado'] = float(kwargs['capital_alocado'])
            if kwargs['capital_alocado'] < 0:
                raise ValueError("Capital não pode ser negativo.")
        except (TypeError, ValueError):
            raise ValueError("Capital alocado deve ser um número válido.")

    campos_permitidos = ['capital_alocado', 'nome_corretora']
    for campo in campos_permitidos:
        if campo in kwargs:
            if campo == 'nome_corretora':
                kwargs[campo] = kwargs[campo].upper()
            setattr(conta, campo, kwargs[campo])

    try:
        db.session.commit()
        # Sincroniza a alocação (pode ser que a corretora tenha mudado)
        _sincronizar_alocacao(user_id, conta.nome_corretora, conta.capital_alocado)
    except Exception as e:
        db.session.rollback()
        raise ValueError(f"Erro ao salvar: {str(e)}")
    return conta


def desativar_conta(conta_id, user_id):
    """Desativa a conta e remove a alocação correspondente."""
    conta = obter_conta(conta_id, user_id)
    if not conta:
        raise ValueError("Conta não encontrada.")
    conta.ativo = False
    db.session.commit()
    # Remove a alocação de corretora associada (para que a fatura não exija mais aquela corretora)
    _remover_sincronizacao(user_id, conta.nome_corretora)
    return conta


def bloquear_conta(conta_id, user_id, bloqueado):
    """Altera o status de bloqueio da conta (admin apenas)."""
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