"""
Serviço de licenças – Responsável por toda lógica de geração, validação e expiração.
Tipos:
- semanal: para clientes comissão, válida até domingo 23:59, geração permitida apenas em dias úteis.
- vitalicia: para clientes compra, válida para sempre (não expira).
"""

from datetime import datetime, timedelta
import pytz
from app import db
from app.models import Fatura, LicencaCliente, User

tz_br = pytz.timezone('America/Sao_Paulo')


# ============================================================
# AUXILIARES
# ============================================================

def proxima_segunda_00h00(data_ref=None):
    """Retorna datetime da próxima segunda-feira às 00:00 (horário BR)."""
    if data_ref is None:
        data_ref = datetime.now(tz_br)
    dias_para_segunda = (7 - data_ref.weekday()) % 7
    if dias_para_segunda == 0:
        dias_para_segunda = 7   # se hoje é segunda, vai para a próxima
    proxima = data_ref + timedelta(days=dias_para_segunda)
    return proxima.replace(hour=0, minute=0, second=0, microsecond=0)


def obter_semana_id(data_ref=None):
    """
    Retorna o identificador único da semana, baseado no último domingo.
    Fórmula idêntica ao JavaScript do gerador original:
        semana_id = floor(timestamp_utc_do_ultimo_domingo / 86400000)
    """
    if data_ref is None:
        data_ref = datetime.now(tz_br).date()
    # Encontrar o domingo anterior ou igual a data_ref
    dias_para_domingo = data_ref.weekday()  # segunda=0, domingo=6
    ultimo_domingo = data_ref - timedelta(days=dias_para_domingo + 1 if dias_para_domingo < 6 else 0)
    # Converter para datetime UTC à meia-noite
    dt_utc = datetime(ultimo_domingo.year, ultimo_domingo.month, ultimo_domingo.day, tzinfo=pytz.UTC)
    timestamp_ms = int(dt_utc.timestamp() * 1000)
    return timestamp_ms // 86400000


def gerar_chave_semanal(conta_mt5, semana_id=None):
    """
    Gera chave semanal conforme fórmula: (conta + semana_id) * 7391
    Se semana_id for None, calcula automaticamente.
    """
    if semana_id is None:
        semana_id = obter_semana_id()
    conta = int(conta_mt5) if conta_mt5 else 0
    return str((conta + semana_id) * 7391)


def gerar_chave_vitalicia(conta_mt5):
    """Gera chave vitalícia conforme fórmula: conta * 99999"""
    conta = int(conta_mt5) if conta_mt5 else 0
    return str(conta * 99999)


def calcular_ciclo_anterior(data_ref=None):
    """
    Retorna (inicio_ciclo, fim_ciclo) da semana completa anterior a data_ref.
    Ciclo = sexta (início) a quinta (fim).
    Se data_ref for None, usa hoje.
    """
    if data_ref is None:
        data_ref = datetime.now(tz_br).date()
    # Encontra a sexta anterior ou igual
    dias_para_sexta = (data_ref.weekday() - 4) % 7
    sexta = data_ref - timedelta(days=dias_para_sexta)
    # Se a sexta é hoje, queremos o ciclo anterior
    if sexta == data_ref:
        sexta -= timedelta(days=7)
    inicio = sexta
    fim = inicio + timedelta(days=6)
    return inicio, fim


# ============================================================
# CONSULTAS
# ============================================================

def obter_licenca_ativa(user, tipo=None):
    """
    Retorna a licença ativa (status='ativa') do usuário.
    Se tipo for informado, filtra por ele. Se não, retorna a mais recente.
    """
    query = LicencaCliente.query.filter_by(user_id=user.id, status='ativa')
    if tipo:
        query = query.filter_by(tipo=tipo)
    return query.order_by(LicencaCliente.data_geracao.desc()).first()


def existe_licenca_para_ciclo(user, ciclo_inicio):
    """Verifica se já existe licença (ativa ou expirada) para aquele ciclo."""
    return LicencaCliente.query.filter_by(
        user_id=user.id,
        ciclo_inicio=ciclo_inicio
    ).first() is not None


# ============================================================
# CONDIÇÕES PARA COMISSÃO
# ============================================================

def verificar_condicoes_comissao(user, ciclo_inicio):
    """
    Verifica se o cliente comissão pode gerar licença para o ciclo_inicio.
    Retorna (liberado: bool, mensagem: str, pendencias: dict)
    """
    # 1. Verificar fatura do ciclo
    fatura = Fatura.query.filter_by(user_id=user.id, data_inicio=ciclo_inicio).first()
    if not fatura:
        return False, f"Ciclo {ciclo_inicio.strftime('%d/%m/%Y')} não encontrado.", {}

    # 2. Notas pendentes?
    dias_pendentes = [d for d in fatura.dias if d.status not in ['relatorio_enviado', 'isento']]
    if dias_pendentes:
        return False, f"Existem {len(dias_pendentes)} dias com notas pendentes.", {'notas_pendentes': [d.data_pregao.strftime('%d/%m') for d in dias_pendentes]}

    # 3. Pagamento (apenas para comissão não isento)
    if not user.is_isento:
        if fatura.status != 'pago':
            return False, "Pagamento deste ciclo ainda não foi confirmado pela administração.", {'pagamento_pendente': True}

    # 4. Já existe licença para este ciclo?
    if existe_licenca_para_ciclo(user, ciclo_inicio):
        return False, "Uma licença já foi gerada para este ciclo. Você pode visualizá-la em 'Minhas Licenças'.", {'licenca_ja_existe': True}

    return True, "Condições atendidas.", {}


# ============================================================
# GERAÇÃO DE LICENÇAS
# ============================================================

def gerar_licenca_comissao(user, conta_mt5, semana_id=None):
    """
    Gera uma nova licença semanal para o cliente comissão.
    Retorna (chave, mensagem, licenca_obj).
    """
    # Obter ciclo anterior (o que deve ser validado)
    ciclo_inicio, ciclo_fim = calcular_ciclo_anterior()
    
    # Verificar condições novamente (segurança)
    liberado, msg, _ = verificar_condicoes_comissao(user, ciclo_inicio)
    if not liberado:
        return None, msg, None
    
    # Gerar chave
    chave = gerar_chave_semanal(conta_mt5, semana_id)
    
    # Data de expiração: domingo 23:59 da semana atual (ajustar)
    # Como o ciclo_inicio é sexta, o domingo seguinte é ciclo_inicio + 2 dias?
    # Para simplificar, usamos a função proxima_segunda_00h00 e subtraímos 1 minuto?
    # Melhor: expirar no domingo 23:59
    hoje = datetime.now(tz_br).date()
    dias_para_domingo = (6 - hoje.weekday()) % 7  # domingo = 6
    domingo = hoje + timedelta(days=dias_para_domingo)
    data_expiracao = datetime(domingo.year, domingo.month, domingo.day, 23, 59, 59, tzinfo=tz_br)
    
    nova_licenca = LicencaCliente(
        user_id=user.id,
        chave_licenca=chave,
        ciclo_inicio=ciclo_inicio,
        ciclo_fim=ciclo_fim,
        tipo='semanal',
        data_expiracao=data_expiracao,
        status='ativa',
        conta_mt5=conta_mt5
    )
    db.session.add(nova_licenca)
    db.session.commit()
    
    return chave, "Licença semanal gerada com sucesso.", nova_licenca


def gerar_licenca_vitalicia(user, conta_mt5):
    """
    Gera uma nova licença vitalícia para o cliente compra.
    Retorna (chave, mensagem, licenca_obj).
    """
    # Verificar se já existe licença vitalícia ativa
    existente = obter_licenca_ativa(user, tipo='vitalicia')
    if existente:
        return existente.chave_licenca, "Licença vitalícia já existente.", existente
    
    chave = gerar_chave_vitalicia(conta_mt5)
    
    # Para vitalícia, data_expiracao = None, status = 'ativa'
    nova_licenca = LicencaCliente(
        user_id=user.id,
        chave_licenca=chave,
        ciclo_inicio=datetime.now(tz_br).date(),  # data de referência
        ciclo_fim=datetime.now(tz_br).date(),     # não usado
        tipo='vitalicia',
        data_expiracao=None,
        status='ativa',
        conta_mt5=conta_mt5
    )
    db.session.add(nova_licenca)
    db.session.commit()
    
    return chave, "Licença vitalícia gerada com sucesso.", nova_licenca


def salvar_conta_mt5_e_gerar_vitalicia_se_necessario(user, nova_conta):
    """
    Atualiza a conta MT5 do usuário. Se o usuário for do tipo compra e ainda não tiver
    licença vitalícia ativa, gera automaticamente.
    Retorna (licenca_gerada, chave_licenca, mensagem)
    """
    user.conta_mt5 = nova_conta
    db.session.commit()
    
    if user.modelo_negocio == 'compra':
        licenca = obter_licenca_ativa(user, tipo='vitalicia')
        if not licenca:
            chave, msg, _ = gerar_licenca_vitalicia(user, nova_conta)
            return True, chave, msg
        else:
            return False, licenca.chave_licenca, "Licença vitalícia já existente."
    return False, None, "Conta MT5 salva (usuário não é compra)."


# ============================================================
# EXPIRAÇÃO SEMANAL
# ============================================================

def expirar_licencas_semanais():
    """
    Marca como expiradas todas as licenças semanais cuja data_expiracão já passou.
    Deve ser chamada por um job agendado (GitHub Actions) toda segunda-feira às 00:00.
    """
    agora = datetime.now(tz_br)
    licencas = LicencaCliente.query.filter(
        LicencaCliente.tipo == 'semanal',
        LicencaCliente.status == 'ativa',
        LicencaCliente.data_expiracao < agora
    ).all()
    
    for lic in licencas:
        lic.status = 'expirada'
    
    db.session.commit()
    return len(licencas)
