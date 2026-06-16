"""
Serviço de parcelas unificado para clientes compra.

Fornece funções para:
- Gerar as 10 parcelas de um novo cliente compra (com ou sem conta MT5 associada).
- Gerar parcelas específicas para uma conta MT5.
- Contar quantas indicações de um usuário já pagaram a entrada.
- Calcular o prêmio acumulado do indicador.
- Verificar se todas as parcelas de um cliente (ou conta) foram pagas.
"""

from datetime import datetime, timedelta
import pytz
from app.models import ParcelaCompra, User, ContaMT5Cliente
from app import db

tz_br = pytz.timezone('America/Sao_Paulo')


def gerar_parcelas_compra_unificado(user_id: int, conta_mt5_id: int = None, data_inicio: datetime.date = None):
    """
    Gera as 10 parcelas para um cliente compra.

    Parcelas:
    - Parcela 1 (ordem=1): R$ 3.000,00 – vencimento = data_inicio (hoje)
    - Parcelas 2 a 10 (ordem=2..10): R$ 500,00 cada – vencimento semanal (sábados)

    Args:
        user_id (int): ID do usuário (cliente compra)
        conta_mt5_id (int, optional): ID da conta MT5 associada (se houver)
        data_inicio (date, optional): Data de início (vencimento da primeira parcela).
                                     Se None, usa a data atual (horário de Brasília).

    Returns:
        list: Lista de objetos ParcelaCompra (prontos para db.session.add_all)
    """
    if data_inicio is None:
        data_inicio = datetime.now(tz_br).date()

    parcelas = []

    # Parcela 1 – entrada (R$ 3.000,00)
    p1 = ParcelaCompra(
        user_id=user_id,
        conta_mt5_id=conta_mt5_id,
        ordem=1,
        valor=3000.0,
        data_vencimento=data_inicio,
        status='pendente'
    )
    parcelas.append(p1)

    # Encontra o primeiro sábado após data_inicio
    dias_para_sabado = (5 - data_inicio.weekday()) % 7
    if dias_para_sabado == 0:
        dias_para_sabado = 7
    primeiro_sabado = data_inicio + timedelta(days=dias_para_sabado)

    # Parcelas 2 a 10 – semanais (sábados)
    for i in range(2, 11):
        vencimento = primeiro_sabado + timedelta(days=7 * (i - 2))
        parcela = ParcelaCompra(
            user_id=user_id,
            conta_mt5_id=conta_mt5_id,
            ordem=i,
            valor=500.0,
            data_vencimento=vencimento,
            status='pendente'
        )
        parcelas.append(parcela)

    return parcelas


def gerar_parcelas_para_conta(conta_mt5_id: int, data_inicio: datetime.date = None):
    """
    Gera as 10 parcelas específicas para uma conta MT5.

    Args:
        conta_mt5_id (int): ID da conta MT5
        data_inicio (date, optional): Data de início. Se None, usa a data atual.

    Returns:
        list: Lista de objetos ParcelaCompra (prontos para db.session.add_all)
    """
    conta = ContaMT5Cliente.query.get(conta_mt5_id)
    if not conta:
        raise ValueError("Conta MT5 não encontrada.")
    if not conta.ativo:
        raise ValueError("Conta MT5 inativa.")

    # Verifica se já existem parcelas para esta conta
    existentes = ParcelaCompra.query.filter_by(conta_mt5_id=conta_mt5_id).first()
    if existentes:
        raise ValueError("Esta conta MT5 já possui parcelas geradas.")

    return gerar_parcelas_compra_unificado(conta.user_id, conta_mt5_id, data_inicio)


def contar_indicacoes_com_entrada_paga(user_id: int) -> int:
    """
    Conta quantos clientes indicados por um usuário já pagaram a parcela de entrada (ordem=1).

    Args:
        user_id (int): ID do indicador.

    Returns:
        int: Número de indicações com parcela 1 status='pago'.
    """
    indicados = User.query.filter_by(indicador_id=user_id, is_indicado=True).all()
    count = 0
    for indicado in indicados:
        parcela_entrada = ParcelaCompra.query.filter_by(
            user_id=indicado.id,
            ordem=1,
            status='pago'
        ).first()
        if parcela_entrada:
            count += 1
    return count


def calcular_premio_acumulado(user_id: int) -> dict:
    """
    Calcula o prêmio acumulado do indicador.

    Args:
        user_id (int): ID do indicador.

    Returns:
        dict: {
            'quantidade_elegivel': int,
            'valor_acumulado': float,
            'pode_solicitar': bool
        }
    """
    qtd = contar_indicacoes_com_entrada_paga(user_id)
    valor_acumulado = qtd * 1000.0
    pode_solicitar = qtd >= 7
    return {
        'quantidade_elegivel': qtd,
        'valor_acumulado': valor_acumulado,
        'pode_solicitar': pode_solicitar
    }


def todas_parcelas_pagas(user_id: int, conta_mt5_id: int = None) -> bool:
    """
    Verifica se todas as parcelas de um cliente (ou conta específica) foram pagas.

    Args:
        user_id (int): ID do usuário.
        conta_mt5_id (int, optional): ID da conta MT5. Se fornecido, verifica apenas as parcelas da conta.

    Returns:
        bool: True se todas as parcelas estão pagas, False caso contrário.
    """
    query = ParcelaCompra.query.filter_by(user_id=user_id)
    if conta_mt5_id is not None:
        query = query.filter_by(conta_mt5_id=conta_mt5_id)

    total = query.count()
    if total == 0:
        return False
    pagas = query.filter_by(status='pago').count()
    return total == pagas


def parcelas_por_conta(conta_mt5_id: int):
    """
    Retorna todas as parcelas de uma conta MT5 específica.

    Args:
        conta_mt5_id (int): ID da conta MT5.

    Returns:
        list: Lista de objetos ParcelaCompra ordenados por ordem.
    """
    return ParcelaCompra.query.filter_by(conta_mt5_id=conta_mt5_id).order_by(ParcelaCompra.ordem).all()


def tem_parcelas_pendentes_por_conta(conta_mt5_id: int) -> bool:
    """
    Verifica se uma conta MT5 possui parcelas pendentes.

    Args:
        conta_mt5_id (int): ID da conta MT5.

    Returns:
        bool: True se há alguma parcela pendente, False caso contrário.
    """
    pendentes = ParcelaCompra.query.filter_by(
        conta_mt5_id=conta_mt5_id,
        status='pendente'
    ).first()
    return pendentes is not None


def obter_primeira_parcela_pendente_por_conta(conta_mt5_id: int):
    """
    Retorna a primeira parcela pendente de uma conta MT5 (ordem mais baixa).

    Args:
        conta_mt5_id (int): ID da conta MT5.

    Returns:
        ParcelaCompra or None: A primeira parcela pendente ou None se não houver.
    """
    return ParcelaCompra.query.filter_by(
        conta_mt5_id=conta_mt5_id,
        status='pendente'
    ).order_by(ParcelaCompra.ordem).first()