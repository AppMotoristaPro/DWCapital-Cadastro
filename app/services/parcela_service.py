"""
Serviço de parcelas unificado para clientes compra (programa de indicação).

Fornece funções para:
- Gerar as 10 parcelas de um novo cliente compra: entrada R$ 3.000 + 9x R$ 500 semanais.
- Contar quantas indicações de um usuário já pagaram a entrada (parcela 1).
- Calcular o prêmio acumulado do indicador.
"""

from datetime import datetime, timedelta
import pytz
from app.models import ParcelaCompra, User

tz_br = pytz.timezone('America/Sao_Paulo')


def gerar_parcelas_compra_unificado(user_id: int, data_inicio: datetime.date = None):
    """
    Gera as 10 parcelas para um novo cliente compra (modelo unificado).
    
    Parcelas:
    - Parcela 1 (ordem=1): R$ 3.000,00 – vencimento = data_inicio (hoje)
    - Parcelas 2 a 10 (ordem=2..10): R$ 500,00 cada – vencimento semanal (sábados)
    
    Args:
        user_id (int): ID do usuário (cliente compra)
        data_inicio (date, optional): Data de início (vencimento da primeira parcela).
                                     Se None, usa a data atual (horário de Brasília).
    
    Returns:
        list: Lista de objetos ParcelaCompra (já criados em memória, prontos para db.session.add_all)
    """
    if data_inicio is None:
        data_inicio = datetime.now(tz_br).date()
    
    parcelas = []
    
    # Parcela 1 – entrada (R$ 3.000,00)
    p1 = ParcelaCompra(
        user_id=user_id,
        ordem=1,
        valor=3000.0,
        data_vencimento=data_inicio,
        status='pendente'
    )
    parcelas.append(p1)
    
    # Encontra o primeiro sábado após data_inicio
    # weekday: segunda=0, terça=1, ..., sábado=5, domingo=6
    dias_para_sabado = (5 - data_inicio.weekday()) % 7
    if dias_para_sabado == 0:
        dias_para_sabado = 7  # se já for sábado, vai para o próximo
    primeiro_sabado = data_inicio + timedelta(days=dias_para_sabado)
    
    # Parcelas 2 a 10 – semanais (sábados)
    for i in range(2, 11):
        vencimento = primeiro_sabado + timedelta(days=7 * (i-2))
        parcela = ParcelaCompra(
            user_id=user_id,
            ordem=i,
            valor=500.0,
            data_vencimento=vencimento,
            status='pendente'
        )
        parcelas.append(parcela)
    
    return parcelas


def contar_indicacoes_com_entrada_paga(user_id: int) -> int:
    """
    Conta quantos clientes indicados por um usuário já pagaram a parcela de entrada (ordem=1).
    
    Args:
        user_id (int): ID do indicador.
    
    Returns:
        int: Número de indicações (com is_indicado=True) que possuem a parcela 1 com status='pago'.
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