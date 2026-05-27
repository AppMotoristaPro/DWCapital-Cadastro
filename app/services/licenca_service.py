"""
Serviço de licenças – responsável por verificar condições e gerar chaves de licença.
Regra: licença pode ser gerada apenas aos SÁBADOS, para o ciclo completo (sexta a quinta).
"""

from datetime import datetime, timedelta
import pytz
from app import db
from app.models import Fatura, LicencaCliente, User
import secrets  # para gerar placeholder (substituir pelo motor real depois)

tz_br = pytz.timezone('America/Sao_Paulo')

def calcular_ciclo_por_data(data_referencia=None):
    """
    Dada uma data de referência (padrão = hoje), retorna (inicio_ciclo, fim_ciclo)
    onde inicio_ciclo é a sexta anterior e fim_ciclo é a quinta seguinte.
    """
    if data_referencia is None:
        data_referencia = datetime.now(tz_br).date()
    # Descobre quantos dias faltam para voltar à última sexta
    dias_para_sexta = (data_referencia.weekday() - 4) % 7
    inicio_ciclo = data_referencia - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6)
    return inicio_ciclo, fim_ciclo

def verificar_condicoes_licenca(user, ciclo_inicio):
    """
    Verifica se um cliente pode gerar licença para o ciclo informado.
    Retorna (liberado: bool, mensagem: str, pendencias: dict)
    """
    pendencias = {}

    # 1. Buscar a fatura do ciclo
    fatura = Fatura.query.filter_by(user_id=user.id, data_inicio=ciclo_inicio).first()
    if not fatura:
        return False, f"Ciclo com início em {ciclo_inicio.strftime('%d/%m/%Y')} não encontrado. Contate o suporte.", pendencias

    # 2. Verificar notas: todos os dias devem estar como 'relatorio_enviado' ou 'isento'
    dias_pendentes = []
    for dia in fatura.dias:
        if dia.status not in ['relatorio_enviado', 'isento']:
            dias_pendentes.append(dia.data_pregao.strftime('%d/%m/%Y'))
    if dias_pendentes:
        pendencias['notas_faltando'] = dias_pendentes
        return False, f"Notas pendentes para os dias: {', '.join(dias_pendentes)}", pendencias

    # 3. Verificar pagamento (apenas para comissionados não isentos)
    if user.modelo_negocio == 'comissao' and not user.is_isento:
        if fatura.status != 'pago':
            pendencias['pagamento_pendente'] = True
            return False, "Pagamento do ciclo pendente. Aguarde a confirmação da tesouraria.", pendencias

    # 4. Verificar se já existe licença para este ciclo
    licenca_existente = LicencaCliente.query.filter_by(user_id=user.id, ciclo_inicio=ciclo_inicio).first()
    if licenca_existente:
        pendencias['licenca_existente'] = True
        return False, "Licença já foi gerada para este ciclo. Uma nova licença só será liberada no próximo ciclo.", pendencias

    return True, "Condições atendidas. Licença pode ser gerada.", pendencias

def gerar_chave_licenca(user, ciclo_inicio):
    """
    Gera uma nova chave de licença.
    ATENÇÃO: esta é uma implementação PLACEHOLDER.
    Substituir pela chamada ao motor externo real (API ou subprocesso) quando disponível.
    Retorna (chave: str, mensagem: str).
    """
    # ==============================================================
    # TODO: INTEGRAR MOTOR EXTERNO DE LICENÇAS AQUI
    # Exemplo de chamada fictícia:
    #   import requests
    #   resp = requests.post('https://api.licencas.com/gerar', json={'cliente_id': user.id, ...})
    #   chave = resp.json().get('chave')
    # ==============================================================

    # Placeholder: gera uma chave fictícia (apenas para testes)
    chave_placeholder = f"LIC-{user.id}-{secrets.token_hex(6).upper()}"

    # Salva a licença no banco
    nova_licenca = LicencaCliente(
        user_id=user.id,
        chave_licenca=chave_placeholder,
        ciclo_inicio=ciclo_inicio,
        ciclo_fim=ciclo_inicio + timedelta(days=6)
    )
    db.session.add(nova_licenca)
    db.session.commit()

    return chave_placeholder, "Licença gerada com sucesso (modo desenvolvimento)."
