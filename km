from datetime import datetime, timedelta
import pytz
import os
from app import db
from app.models import Fatura, LicencaCliente, User, ProdutoRobo, ContaMT5Cliente
from sqlalchemy.exc import IntegrityError
from app.services.parcela_service import todas_parcelas_pagas
from app.services.conta_mt5_service import verificar_licenca_comprada

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


def is_conta_bloqueada(conta_id, user_id):
    """Verifica se uma conta específica está bloqueada (admin) ou inativa."""
    conta = ContaMT5Cliente.query.filter_by(id=conta_id, user_id=user_id).first()
    return conta is None or not conta.ativo or conta.bloqueada


# ============================================================
# AUXILIARES
# ============================================================

def obter_numero_conta_por_id(conta_id, user_id):
    """Retorna o número da conta MT5 a partir do ID, validando pertencimento ao usuário."""
    conta = ContaMT5Cliente.query.filter_by(id=conta_id, user_id=user_id, ativo=True).first()
    if not conta:
        return None
    return conta.numero_conta


def proxima_segunda_00h00(data_ref=None):
    """Retorna datetime da próxima segunda-feira às 00:00 (horário BR)."""
    if data_ref is None:
        data_ref = datetime.now(tz_br)
    dias_para_segunda = (7 - data_ref.weekday()) % 7
    if dias_para_segunda == 0:
        dias_para_segunda = 7
    proxima = data_ref + timedelta(days=dias_para_segunda)
    return proxima.replace(hour=0, minute=0, second=0, microsecond=0)


def obter_semana_id_mql5(data_ref=None):
    """
    Retorna o número da semana (1-52) baseado no dia do ano, conforme MQL5.
    """
    if data_ref is None:
        data_ref = datetime.now(tz_br).date()
    inicio_ano = datetime(data_ref.year, 1, 1).date()
    dias_passados = (data_ref - inicio_ano).days
    return (dias_passados // 7) + 1


def gerar_chave_semanal(conta_mt5_numero, produto_id, semana_id=None, ano=None):
    """
    Gera chave semanal conforme nova fórmula:
        (conta + semanaId + ano + codigo_algoritmo) * 7391
    Se semana_id for None, calcula automaticamente com MQL5.
    Se ano for None, usa ano atual.
    """
    if semana_id is None:
        semana_id = obter_semana_id_mql5()
    if ano is None:
        ano = datetime.now(tz_br).year
    conta = int(conta_mt5_numero) if conta_mt5_numero else 0
    produto = ProdutoRobo.query.get(produto_id)
    codigo = produto.codigo_algoritmo if produto else 700
    return str((conta + semana_id + ano + codigo) * 7391)


def gerar_chave_vitalicia(conta_mt5_numero, produto_id=None):
    """
    Gera chave vitalícia conforme nova fórmula:
        (conta + codigo_algoritmo) * 8888 + 7391
    Se produto_id não informado ou produto não encontrado, usa codigo=700.
    """
    conta = int(conta_mt5_numero) if conta_mt5_numero else 0
    codigo = 700
    if produto_id:
        produto = ProdutoRobo.query.get(produto_id)
        if produto:
            codigo = produto.codigo_algoritmo
    return str((conta + codigo) * 8888 + 7391)


def gerar_licenca_vitalicia(user, conta_mt5_id, produto_id=None):
    """
    Gera uma licença vitalícia usando a nova fórmula, vinculada a uma conta MT5 específica.
    Se já existir uma licença vitalícia ativa para essa conta, cancela a anterior.
    Para clientes modelo compra, verifica se a licença foi comprada e se todas as parcelas estão pagas.
    Retorna (chave, mensagem, licenca_obj)
    """
    if is_acesso_robot_bloqueado(user):
        return None, "Cliente bloqueado para gerar licenças.", None

    conta = ContaMT5Cliente.query.filter_by(id=conta_mt5_id, user_id=user.id, ativo=True).first()
    if not conta:
        return None, "Conta MT5 não encontrada ou inativa.", None
    if conta.bloqueada:
        return None, "Esta conta MT5 está bloqueada pelo administrador.", None

    # ==================== VERIFICAÇÃO PARA CLIENTES COMPRA ====================
    if user.modelo_negocio == 'compra':
        # 1. Verifica se a licença foi comprada para esta conta
        if not verificar_licenca_comprada(conta_mt5_id, user.id):
            return None, "Licença não adquirida para esta conta. Compre uma licença em 'Minhas Contas'.", None

        # 2. Verifica se existem parcelas associadas a esta conta
        from app.models import ParcelaCompra
        parcelas_conta = ParcelaCompra.query.filter_by(conta_mt5_id=conta_mt5_id).all()
        if not parcelas_conta:
            return None, "Esta conta MT5 não possui parcelas associadas. É necessário realizar a compra da licença para esta conta.", None

        # 3. Verifica se todas as parcelas da conta estão pagas
        if not todas_parcelas_pagas(user.id, conta_mt5_id):
            return None, "Existem parcelas pendentes para esta conta. Quite todas as parcelas para obter a licença vitalícia.", None

    numero_conta = conta.numero_conta

    # Cancela licença vitalícia existente para esta mesma conta (se houver)
    licenca_existente = LicencaCliente.query.filter_by(
        user_id=user.id, conta_mt5_id=conta_mt5_id, tipo='vitalicia', status='ativa'
    ).first()
    if licenca_existente:
        licenca_existente.status = 'cancelada'
        db.session.add(licenca_existente)

    chave = gerar_chave_vitalicia(numero_conta, produto_id)

    nova_licenca = LicencaCliente(
        user_id=user.id,
        conta_mt5_id=conta_mt5_id,
        chave_licenca=chave,
        ciclo_inicio=datetime.now(tz_br).date(),
        ciclo_fim=datetime.now(tz_br).date(),
        tipo='vitalicia',
        data_expiracao=None,
        status='ativa'
    )
    db.session.add(nova_licenca)
    db.session.commit()
    return chave, "Licença vitalícia gerada com sucesso.", nova_licenca


def calcular_ciclo_por_data(data_ref=None):
    """Retorna (inicio_ciclo, fim_ciclo) onde inicio_ciclo é a sexta anterior e fim_ciclo a quinta seguinte."""
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
    """
    if data_ref is None:
        data_ref = datetime.now(tz_br).date()
    dias_para_sexta = (data_ref.weekday() - 4) % 7
    sexta_atual = data_ref - timedelta(days=dias_para_sexta)
    inicio = sexta_atual - timedelta(days=7)
    fim = inicio + timedelta(days=6)
    return inicio, fim


# ============================================================
# CONSULTAS
# ============================================================

def obter_licenca_ativa_por_conta(conta_mt5_id, tipo=None):
    """Retorna a licença ativa para uma conta específica. Se tipo informado, filtra por ele."""
    query = LicencaCliente.query.filter_by(conta_mt5_id=conta_mt5_id, status='ativa')
    if tipo:
        query = query.filter_by(tipo=tipo)
    return query.order_by(LicencaCliente.data_geracao.desc()).first()


def existe_licenca_para_ciclo(conta_mt5_id, ciclo_inicio):
    """Verifica se já existe licença (não expirada) para aquela conta naquele ciclo."""
    return LicencaCliente.query.filter(
        LicencaCliente.conta_mt5_id == conta_mt5_id,
        LicencaCliente.ciclo_inicio == ciclo_inicio,
        LicencaCliente.status != 'expirada'
    ).first() is not None


# ============================================================
# CONDIÇÕES PARA GERAÇÃO (UNIFICADA) – APENAS PARA LICENÇA SEMANAL
# ============================================================

def verificar_condicoes_comissao(user, ciclo_inicio):
    """
    Verifica se o cliente pode gerar licença semanal para o ciclo_inicio informado.
    (as condições são por cliente, independente da conta)
    Retorna (status, mensagem, pendencias, licenca_existente)
    """
    fatura = Fatura.query.filter_by(user_id=user.id, data_inicio=ciclo_inicio).first()
    if not fatura:
        return True, "Cliente novo (sem ciclo anterior). Licença liberada imediatamente.", {}, None

    dias_pendentes = [d for d in fatura.dias if d.status not in ['relatorio_enviado', 'isento']]
    if dias_pendentes:
        return False, f"Existem {len(dias_pendentes)} dias com notas pendentes.", {'notas_pendentes': [d.data_pregao.strftime('%d/%m') for d in dias_pendentes]}, None

    if user.modelo_negocio == 'comissao' and not user.is_isento:
        if fatura.status != 'pago':
            return False, "Pagamento deste ciclo ainda não foi confirmado pela administração.", {'pagamento_pendente': True}, None

    # Não verifica licença existente aqui (será verificado por conta)
    return True, "Condições atendidas.", {}, None


# ============================================================
# GERAÇÃO DE LICENÇA SEMANAL – COM CONTA_MT5_ID (CORRIGIDA DEFINITIVA)
# ============================================================

def gerar_licenca_comissao(user, conta_mt5_id, produto_id, semana_id=None):
    """
    Gera uma nova licença semanal vinculada a uma conta MT5 específica e a um produto.
    Para clientes compra, verifica se a licença foi comprada para a conta.
    Retorna (chave, mensagem, licenca_obj, ja_existente)
    """
    if is_acesso_robot_bloqueado(user):
        return None, "Seu acesso ao robô está bloqueado. Entre em contato com o suporte.", None, False

    # Validar conta
    conta = ContaMT5Cliente.query.filter_by(id=conta_mt5_id, user_id=user.id, ativo=True).first()
    if not conta:
        return None, "Conta MT5 não encontrada ou inativa.", None, False
    if conta.bloqueada:
        return None, "Esta conta MT5 está bloqueada pelo administrador.", None, False

    # ==================== VERIFICAÇÃO PARA CLIENTES COMPRA ====================
    if user.modelo_negocio == 'compra':
        if not verificar_licenca_comprada(conta_mt5_id, user.id):
            return None, "Licença não adquirida para esta conta. Compre uma licença em 'Minhas Contas'.", None, False

    # O ciclo anterior é usado apenas para verificar condições de pagamento
    ciclo_inicio, ciclo_fim = calcular_ciclo_anterior()

    # Verificar condições gerais do cliente (usa o ciclo anterior)
    status, msg, _, _ = verificar_condicoes_comissao(user, ciclo_inicio)
    if not status:
        return None, msg, None, False

    # Verificar se já existe licença para esta conta neste ciclo (anterior)
    licenca_existente = LicencaCliente.query.filter(
        LicencaCliente.conta_mt5_id == conta_mt5_id,
        LicencaCliente.ciclo_inicio == ciclo_inicio,
        LicencaCliente.status != 'expirada'
    ).first()
    if licenca_existente:
        return licenca_existente.chave_licenca, "Licença já existente para este ciclo.", licenca_existente, True

    # ========== CORREÇÃO DEFINITIVA: calcular semana com base no CICLO ATUAL ==========
    # Usamos o início do ciclo atual (não o anterior) para gerar a chave.
    # Isso garante que a chave seja válida para o robô, que valida com a semana atual.
    if semana_id is None:
        ciclo_atual_inicio, _ = calcular_ciclo_por_data()  # ciclo atual (sexta a quinta)
        data_ref = ciclo_atual_inicio
        semana_id = obter_semana_id_mql5(data_ref)
        ano = data_ref.year
    else:
        ano = datetime.now(tz_br).year

    chave = gerar_chave_semanal(conta.numero_conta, produto_id, semana_id, ano)

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
        conta_mt5_id=conta_mt5_id,
        chave_licenca=chave,
        ciclo_inicio=ciclo_inicio,   # ciclo anterior (para controle de pagamento)
        ciclo_fim=ciclo_fim,
        tipo='semanal',
        data_expiracao=data_expiracao_utc,
        status='ativa'
    )
    db.session.add(nova_licenca)

    try:
        db.session.commit()
        return chave, "Licença semanal gerada com sucesso.", nova_licenca, False
    except IntegrityError:
        db.session.rollback()
        # Concorrência: tenta buscar novamente
        licenca_concorrente = LicencaCliente.query.filter(
            LicencaCliente.conta_mt5_id == conta_mt5_id,
            LicencaCliente.ciclo_inicio == ciclo_inicio,
            LicencaCliente.status == 'ativa'
        ).first()
        if licenca_concorrente:
            return licenca_concorrente.chave_licenca, "Licença já existente para este ciclo.", licenca_concorrente, True
        else:
            return None, "Erro de concorrência. Tente novamente.", None, False


def salvar_conta_mt5_e_gerar_vitalicia_se_necessario(user, conta_mt5_id, produto_id=None):
    """
    Este método não é mais necessário porque agora as contas são gerenciadas separadamente.
    Mantido para compatibilidade com chamadas antigas, mas não faz nada.
    """
    return False, None, "Operação não suportada no novo modelo de múltiplas contas."


# ============================================================
# FUNÇÃO DE COMPATIBILIDADE PARA ADMIN
# ============================================================

def obter_licenca_ativa(user, tipo=None):
    """
    Compatibilidade com código antigo (admin). Retorna primeira licença ativa do usuário (qualquer conta).
    """
    query = LicencaCliente.query.filter_by(user_id=user.id, status='ativa')
    if tipo:
        query = query.filter_by(tipo=tipo)
    return query.order_by(LicencaCliente.data_geracao.desc()).first()


# ============================================================
# EXPIRAÇÃO (UNIFICADA)
# ============================================================

def expirar_licencas_semanais():
    """Marca como expiradas todas as licenças cuja data_expiracão já passou."""
    agora_utc = datetime.now(pytz.UTC)
    print(f"[CRON] Verificando licenças ativas com expiração < {agora_utc.isoformat()} (UTC)")

    licencas = LicencaCliente.query.filter(
        LicencaCliente.status == 'ativa',
        LicencaCliente.data_expiracao < agora_utc
    ).all()

    print(f"[CRON] Encontradas {len(licencas)} licenças para expirar.")

    for lic in licencas:
        print(f"[CRON] Expirando licença ID {lic.id} (conta {lic.conta_mt5_id}, tipo {lic.tipo}, expiração {lic.data_expiracao})")
        lic.status = 'expirada'

    db.session.commit()
    return len(licencas)
