from datetime import datetime, timedelta
import pytz
import os
from app import db
from app.models import Fatura, LicencaCliente, User
from sqlalchemy.exc import IntegrityError

tz_br = pytz.timezone('America/Sao_Paulo')


# ============================================================
# MODO TESTE
# ============================================================

def is_modo_teste():
    """Retorna True se a variável TESTE_LICENCA estiver configurada como 'true' (case-insensitive)."""
    return os.environ.get('TESTE_LICENCA', 'false').lower() in ('true', '1', 't')


# ============================================================
# BLOQUEIO DE LICENÇAS
# ============================================================

def is_licenca_bloqueada(user):
    """Retorna True se o cliente está com a geração de licenças bloqueada pelo admin."""
    return getattr(user, 'licenca_bloqueada', False)

def is_acesso_robot_bloqueado(user):
    """Retorna True se o cliente está com o acesso ao robô bloqueado (download e novas licenças)."""
    return getattr(user, 'robot_acesso_bloqueado', False)


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


# ============================================================
# NOVA FÓRMULA PARA LICENÇA VITALÍCIA (PERPÉTUA)
# ============================================================

def gerar_chave_vitalicia_nova(conta_mt5):
    """Gera chave vitalícia conforme nova fórmula: (conta * 8888) + 7391"""
    conta = int(conta_mt5) if conta_mt5 else 0
    return str((conta * 8888) + 7391)


def gerar_licenca_vitalicia(user, conta_mt5):
    """
    Gera uma licença vitalícia (perpétua) usando a nova fórmula.
    Se já existir uma licença vitalícia ativa, cancela a anterior.
    Retorna (chave, mensagem, licenca_obj)
    """
    # Bloqueios
    if is_acesso_robot_bloqueado(user):
        return None, "Cliente bloqueado para gerar licenças.", None
    if not conta_mt5:
        return None, "Conta MT5 não informada.", None

    # Cancela licença vitalícia existente (se houver)
    licenca_existente = LicencaCliente.query.filter_by(
        user_id=user.id, tipo='vitalicia', status='ativa'
    ).first()
    if licenca_existente:
        licenca_existente.status = 'cancelada'
        db.session.add(licenca_existente)

    chave = gerar_chave_vitalicia_nova(conta_mt5)

    nova_licenca = LicencaCliente(
        user_id=user.id,
        chave_licenca=chave,
        ciclo_inicio=datetime.now(tz_br).date(),
        ciclo_fim=datetime.now(tz_br).date(),
        tipo='vitalicia',
        data_expiracao=None,
        status='ativa',
        conta_mt5=conta_mt5
    )
    db.session.add(nova_licenca)
    db.session.commit()
    return chave, "Licença vitalícia gerada com sucesso.", nova_licenca


def calcular_ciclo_por_data(data_ref=None):
    """
    Dada uma data de referência (padrão = hoje), retorna (inicio_ciclo, fim_ciclo)
    onde inicio_ciclo é a sexta anterior e fim_ciclo é a quinta seguinte.
    """
    if data_ref is None:
        data_ref = datetime.now(tz_br).date()
    dias_para_sexta = (data_ref.weekday() - 4) % 7
    inicio_ciclo = data_ref - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6)
    return inicio_ciclo, fim_ciclo


def calcular_ciclo_anterior(data_ref=None):
    """
    Retorna (inicio_ciclo, fim_ciclo) da semana COMPLETAMENTE ANTERIOR à data_ref.
    Ciclo = sexta (início) a quinta (fim).
    Exemplo: se hoje é 2026-06-01 (segunda), o ciclo atual começa em 2026-05-29 (sexta) e termina em 2026-06-04 (quinta).
    O ciclo anterior começa em 2026-05-22 (sexta) e termina em 2026-05-28 (quinta).
    """
    if data_ref is None:
        data_ref = datetime.now(tz_br).date()
    # Encontra o início do ciclo atual
    dias_para_sexta = (data_ref.weekday() - 4) % 7
    sexta_atual = data_ref - timedelta(days=dias_para_sexta)
    # O ciclo anterior começa 7 dias antes
    inicio = sexta_atual - timedelta(days=7)
    fim = inicio + timedelta(days=6)
    return inicio, fim


# ============================================================
# CONSULTAS
# ============================================================

def obter_licenca_ativa(user, tipo=None):
    """
    Retorna a licença ativa (status='ativa') do usuário.
    Se tipo for informado, filtra por ele.
    """
    query = LicencaCliente.query.filter_by(user_id=user.id, status='ativa')
    if tipo:
        query = query.filter_by(tipo=tipo)
    return query.order_by(LicencaCliente.data_geracao.desc()).first()


def existe_licenca_para_ciclo(user, ciclo_inicio):
    """Verifica se já existe licença (não expirada) para aquele ciclo."""
    return LicencaCliente.query.filter(
        LicencaCliente.user_id == user.id,
        LicencaCliente.ciclo_inicio == ciclo_inicio,
        LicencaCliente.status != 'expirada'
    ).first() is not None


# ============================================================
# CONDIÇÕES PARA GERAÇÃO (UNIFICADA) – APENAS PARA LICENÇA SEMANAL
# ============================================================

def verificar_condicoes_comissao(user, ciclo_inicio):
    """
    Verifica se o cliente pode gerar licença semanal para o ciclo_inicio informado.
    Funciona para ambos os modelos (comissão e compra), com diferença:
    - Comissão não isento: exige pagamento.
    - Compra: não exige pagamento (apenas notas enviadas).
    Retorna (status, mensagem, pendencias, licenca_existente)
    """
    # 1. Verificar se o cliente possui fatura para este ciclo específico
    fatura = Fatura.query.filter_by(user_id=user.id, data_inicio=ciclo_inicio).first()

    if not fatura:
        return True, "Cliente novo (sem ciclo anterior). Licença liberada imediatamente.", {}, None

    # Notas pendentes?
    dias_pendentes = [d for d in fatura.dias if d.status not in ['relatorio_enviado', 'isento']]
    if dias_pendentes:
        return False, f"Existem {len(dias_pendentes)} dias com notas pendentes.", {'notas_pendentes': [d.data_pregao.strftime('%d/%m') for d in dias_pendentes]}, None

    # Pagamento (apenas para comissão não isento)
    if user.modelo_negocio == 'comissao' and not user.is_isento:
        if fatura.status != 'pago':
            return False, "Pagamento deste ciclo ainda não foi confirmado pela administração.", {'pagamento_pendente': True}, None

    # Verificar se já existe licença NÃO EXPIRADA para este ciclo
    licenca_existente = LicencaCliente.query.filter(
        LicencaCliente.user_id == user.id,
        LicencaCliente.ciclo_inicio == ciclo_inicio,
        LicencaCliente.status != 'expirada'
    ).first()
    if licenca_existente:
        return "LICENCA_EXISTENTE", "Uma licença já foi gerada para este ciclo.", {}, licenca_existente

    return True, "Condições atendidas.", {}, None


# ============================================================
# GERAÇÃO DE LICENÇA SEMANAL (UNIFICADA)
# ============================================================

def gerar_licenca_comissao(user, conta_mt5, semana_id=None):
    """
    Gera uma nova licença semanal ou retorna a existente (não expirada).
    Funciona para qualquer modelo de negócio (comissão ou compra).
    Retorna (chave, mensagem, licenca_obj, ja_existente)
    """
    if is_acesso_robot_bloqueado(user):
        return None, "Seu acesso ao robô está bloqueado. Entre em contato com o suporte.", None, False

    ciclo_inicio, ciclo_fim = calcular_ciclo_anterior()
    status, msg, _, licenca_existente = verificar_condicoes_comissao(user, ciclo_inicio)

    if status == "LICENCA_EXISTENTE" and licenca_existente:
        return licenca_existente.chave_licenca, msg, licenca_existente, True

    if not status:
        return None, msg, None, False

    chave = gerar_chave_semanal(conta_mt5, semana_id)

    hoje_br = datetime.now(tz_br).date()
    dias_para_proximo_domingo = (6 - hoje_br.weekday()) % 7
    if dias_para_proximo_domingo == 0:
        dias_para_proximo_domingo = 7
    proximo_domingo = hoje_br + timedelta(days=dias_para_proximo_domingo)

    data_expiracao_utc = datetime(
        proximo_domingo.year, proximo_domingo.month, proximo_domingo.day,
        20, 59, 59, tzinfo=pytz.UTC
    )

    nova_licenca = LicencaCliente(
        user_id=user.id,
        chave_licenca=chave,
        ciclo_inicio=ciclo_inicio,
        ciclo_fim=ciclo_fim,
        tipo='semanal',
        data_expiracao=data_expiracao_utc,
        status='ativa',
        conta_mt5=conta_mt5
    )
    db.session.add(nova_licenca)

    try:
        db.session.commit()
        return chave, "Licença semanal gerada com sucesso.", nova_licenca, False
    except IntegrityError:
        db.session.rollback()
        licenca_existente_concorrente = LicencaCliente.query.filter(
            LicencaCliente.user_id == user.id,
            LicencaCliente.ciclo_inicio == ciclo_inicio,
            LicencaCliente.status == 'ativa'
        ).first()
        if licenca_existente_concorrente:
            return licenca_existente_concorrente.chave_licenca, "Licença já existente para este ciclo.", licenca_existente_concorrente, True
        else:
            return None, "Erro de concorrência. Tente novamente.", None, False


def salvar_conta_mt5_e_gerar_vitalicia_se_necessario(user, nova_conta):
    """
    Atualiza a conta MT5 do usuário. Se o usuário for do tipo compra e ainda não tiver
    licença ativa, gera uma licença semanal (não vitalícia).
    """
    user.conta_mt5 = nova_conta
    db.session.commit()

    if user.modelo_negocio == 'compra':
        licenca = obter_licenca_ativa(user, tipo='semanal')
        if not licenca:
            chave, msg, _, _ = gerar_licenca_comissao(user, nova_conta)
            return True, chave, msg
        else:
            return False, licenca.chave_licenca, "Licença já existente para este ciclo."
    return False, None, "Conta MT5 salva (usuário não é compra)."


# ============================================================
# EXPIRAÇÃO (UNIFICADA)
# ============================================================

def expirar_licencas_semanais():
    """
    Marca como expiradas todas as licenças (semanais e vitalícias) cuja data_expiracão já passou.
    Deve ser chamada por um job agendado toda segunda-feira às 00:06 BRT.
    """
    agora_utc = datetime.now(pytz.UTC)
    print(f"[CRON] Verificando licenças ativas com expiração < {agora_utc.isoformat()} (UTC)")

    licencas = LicencaCliente.query.filter(
        LicencaCliente.status == 'ativa',
        LicencaCliente.data_expiracao < agora_utc
    ).all()

    print(f"[CRON] Encontradas {len(licencas)} licenças para expirar.")

    for lic in licencas:
        print(f"[CRON] Expirando licença ID {lic.id} (user {lic.user_id}, tipo {lic.tipo}, expiração {lic.data_expiracao})")
        lic.status = 'expirada'

    db.session.commit()
    return len(licencas)