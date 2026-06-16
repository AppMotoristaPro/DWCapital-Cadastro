"""
Serviço para controle de versão do robô e downloads.
Gerencia a versão ativa, o histórico de downloads por cliente e o bloqueio de múltiplos downloads por conta.
Inclui verificação de licença comprada para clientes compra.
"""

from datetime import datetime
import pytz
import logging
from app import db
from app.models import VersaoRobo, DownloadControle, ProdutoRobo, ContaMT5Cliente, User
from app.services.licenca_service import calcular_ciclo_por_data
from app.services.conta_mt5_service import verificar_licenca_comprada

logger = logging.getLogger(__name__)
tz_br = pytz.timezone('America/Sao_Paulo')


# ========== FUNÇÕES EXISTENTES (adaptadas) ==========

def versao_atual():
    """Retorna o objeto VersaoRobo que está com publicada=True, ou None."""
    return VersaoRobo.query.filter_by(publicada=True).first()


def cliente_ja_baixou_versao(conta_mt5_id, versao_id, ciclo_inicio):
    """Verifica se a conta já baixou uma determinada versão em um ciclo específico."""
    return DownloadControle.query.filter_by(
        conta_mt5_id=conta_mt5_id,
        versao_id=versao_id,
        ciclo_inicio=ciclo_inicio
    ).first() is not None


def registrar_download(conta_mt5_id, versao_id, ciclo_inicio):
    """Registra o download de uma versão por uma conta MT5 em um ciclo."""
    if cliente_ja_baixou_versao(conta_mt5_id, versao_id, ciclo_inicio):
        return False
    novo_download = DownloadControle(
        user_id=ContaMT5Cliente.query.get(conta_mt5_id).user_id,
        conta_mt5_id=conta_mt5_id,
        versao_id=versao_id,
        data_download=datetime.now(tz_br),
        ciclo_inicio=ciclo_inicio
    )
    db.session.add(novo_download)
    db.session.commit()
    return True


def historico_downloads_por_conta(conta_mt5_id):
    """Retorna lista de versões que uma conta específica já baixou."""
    downloads = DownloadControle.query.filter_by(conta_mt5_id=conta_mt5_id)\
        .join(VersaoRobo)\
        .order_by(DownloadControle.data_download.desc()).all()
    historico = []
    for d in downloads:
        historico.append({
            'versao': d.versao.versao,
            'data_download': d.data_download,
            'novidades': d.versao.novidades
        })
    return historico


# ========== NOVAS FUNÇÕES PARA MÚLTIPLOS ROBÔS E MÚLTIPLAS CONTAS ==========

def obter_produtos_ativos():
    """
    Retorna lista de produtos ativos com sua versão publicada (se existir).
    Útil para a tela do cliente.
    """
    produtos = ProdutoRobo.query.filter_by(ativo=True).order_by(ProdutoRobo.ordem).all()
    resultado = []
    for p in produtos:
        versao = VersaoRobo.query.filter_by(produto_id=p.id, publicada=True).first()
        resultado.append({
            'produto': p,
            'versao': versao,
            'disponivel': versao is not None
        })
    return resultado


def ultimo_download_por_produto_e_conta(conta_mt5_id, produto_id):
    """
    Retorna o último registro de DownloadControle para um produto e conta específicos.
    """
    return DownloadControle.query.join(VersaoRobo).filter(
        DownloadControle.conta_mt5_id == conta_mt5_id,
        VersaoRobo.produto_id == produto_id
    ).order_by(DownloadControle.data_download.desc()).first()


def conta_baixou_algum_produto_no_ciclo(conta_mt5_id, ciclo_inicio):
    """
    Retorna o produto_id do primeiro download feito pela conta no ciclo (ou None).
    """
    download = DownloadControle.query.join(VersaoRobo).filter(
        DownloadControle.conta_mt5_id == conta_mt5_id,
        DownloadControle.ciclo_inicio == ciclo_inicio
    ).first()
    if download:
        return download.versao.produto_id
    return None


def liberado_para_download_produto(user, produto_id, ciclo_inicio, conta_mt5_id):
    """
    Verifica se o cliente pode baixar um determinado produto no ciclo atual usando a conta especificada.
    Retorna (bool, mensagem, versao_obj)
    Inclui verificação de licença comprada para clientes compra.
    """
    logger.info(f"[LIBERADO] Iniciando verificação: user={user.id}, produto={produto_id}, ciclo={ciclo_inicio}, conta={conta_mt5_id}")

    # Validar conta
    conta = ContaMT5Cliente.query.filter_by(id=conta_mt5_id, user_id=user.id).first()
    if not conta:
        logger.warning(f"[LIBERADO] Conta não encontrada: {conta_mt5_id}")
        return False, "Conta MT5 não encontrada.", None
    if not conta.ativo:
        logger.warning(f"[LIBERADO] Conta inativa: {conta_mt5_id}")
        return False, "Esta conta MT5 está inativa.", None
    if conta.bloqueada:
        logger.warning(f"[LIBERADO] Conta bloqueada: {conta_mt5_id}")
        return False, "Esta conta MT5 está bloqueada pelo administrador.", None

    # ========== VERIFICAÇÃO DE LICENÇA COMPRADA ==========
    # Para clientes compra, a conta deve ter licenca_comprada = True
    if user.modelo_negocio == 'compra' and not verificar_licenca_comprada(conta_mt5_id, user.id):
        logger.warning(f"[LIBERADO] Licença não comprada para conta {conta_mt5_id}")
        return False, "Licença não adquirida para esta conta. Compre uma licença em 'Minhas Contas'.", None

    # Bloqueio administrativo geral
    if getattr(user, 'robot_acesso_bloqueado', False):
        logger.warning(f"[LIBERADO] Bloqueado: robot_acesso_bloqueado=True")
        return False, "Acesso ao robô bloqueado pelo administrador.", None

    # ========== VÍNCULO VITALÍCIO ==========
    # Se o cliente (modelo compra) já possui um produto vitalício vinculado,
    # ele só pode baixar exatamente aquele produto, independente da conta.
    if user.modelo_negocio == 'compra' and user.produto_vitalicio_id is not None:
        if user.produto_vitalicio_id != produto_id:
            logger.warning(f"[LIBERADO] Bloqueado: usuário tem vínculo vitalício com produto {user.produto_vitalicio_id}, tentou baixar {produto_id}")
            return False, "Você já possui licença vitalícia para outro robô e não pode mais trocar.", None
        logger.info(f"[LIBERADO] Usuário com vínculo vitalício, permitindo download do produto vinculado")

    # Versão publicada do produto?
    versao = VersaoRobo.query.filter_by(produto_id=produto_id, publicada=True).first()
    if not versao:
        logger.warning(f"[LIBERADO] Bloqueado: versão publicada não encontrada para produto_id={produto_id}")
        return False, "Robô indisponível no momento.", None

    logger.info(f"[LIBERADO] Versão encontrada: id={versao.id}, versao={versao.versao}")

    # Verifica se já baixou algum produto neste ciclo para esta conta
    produto_baixado = conta_baixou_algum_produto_no_ciclo(conta_mt5_id, ciclo_inicio)
    logger.info(f"[LIBERADO] produto_baixado no ciclo pela conta: {produto_baixado}")

    if produto_baixado is None:
        logger.info(f"[LIBERADO] Nenhum download neste ciclo para esta conta → liberado")
        return True, "", versao
    else:
        if produto_baixado == produto_id:
            # Já baixou este produto no ciclo: só libera se houve atualização
            ultimo = ultimo_download_por_produto_e_conta(conta_mt5_id, produto_id)
            logger.info(f"[LIBERADO] Último download deste produto pela conta: versao_id={ultimo.versao_id if ultimo else None}, versao_atual_id={versao.id}")
            if ultimo and ultimo.versao_id != versao.id:
                logger.info(f"[LIBERADO] Versão atualizada → liberado")
                return True, "", versao
            else:
                logger.warning(f"[LIBERADO] Bloqueado: já baixou este robô e não foi atualizado")
                return False, "Você já baixou este robô e ele não foi atualizado.", None
        else:
            logger.warning(f"[LIBERADO] Bloqueado: já baixou outro produto (id={produto_baixado}) neste ciclo para esta conta")
            return False, "Você já baixou outro robô para esta conta neste ciclo. Aguarde a próxima semana.", None


def registrar_download_produto(user, versao_obj, ciclo_inicio, conta_mt5_id):
    """
    Registra o download de uma versão de um produto, vinculado a uma conta MT5 e ao ciclo.
    """
    logger.info(f"[REGISTRAR] Tentando registrar: user={user.id}, versao_id={versao_obj.id}, ciclo={ciclo_inicio}, conta={conta_mt5_id}")

    # Verifica se já existe um registro exatamente igual
    existente = DownloadControle.query.filter_by(
        conta_mt5_id=conta_mt5_id,
        versao_id=versao_obj.id,
        ciclo_inicio=ciclo_inicio
    ).first()
    if existente:
        logger.info(f"[REGISTRAR] Registro já existe (id={existente.id}), ignorando")
        return

    novo = DownloadControle(
        user_id=user.id,
        conta_mt5_id=conta_mt5_id,
        versao_id=versao_obj.id,
        data_download=datetime.now(tz_br),
        ciclo_inicio=ciclo_inicio
    )
    db.session.add(novo)
    db.session.commit()
    logger.info(f"[REGISTRAR] Registro criado com sucesso, id={novo.id}")


def obter_produto_baixado_no_ciclo_atual_por_conta(conta_mt5_id):
    """
    Retorna o ID do produto (robô) que a conta baixou no ciclo atual.
    Utilizado para forçar a geração de licença apenas para o robô já baixado por aquela conta.
    Se nenhum download no ciclo atual, retorna None.
    """
    ciclo_inicio, _ = calcular_ciclo_por_data()
    download = DownloadControle.query.join(VersaoRobo).filter(
        DownloadControle.conta_mt5_id == conta_mt5_id,
        DownloadControle.ciclo_inicio == ciclo_inicio
    ).first()
    if download:
        return download.versao.produto_id
    return None