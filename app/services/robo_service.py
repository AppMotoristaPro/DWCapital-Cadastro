"""
Serviço para controle de versão do robô e downloads.
Gerencia a versão ativa, o histórico de downloads por cliente e o bloqueio de múltiplos downloads.
"""

from datetime import datetime
import pytz
from app import db
from app.models import VersaoRobo, DownloadControle, ProdutoRobo
from app.services.licenca_service import calcular_ciclo_por_data

tz_br = pytz.timezone('America/Sao_Paulo')


# ========== FUNÇÕES EXISTENTES ==========

def versao_atual():
    """Retorna o objeto VersaoRobo que está com publicada=True, ou None."""
    return VersaoRobo.query.filter_by(publicada=True).first()


def cliente_ja_baixou(user, versao_id):
    """Verifica se o cliente já baixou uma determinada versão do robô (ignorando ciclo)."""
    return DownloadControle.query.filter_by(user_id=user.id, versao_id=versao_id).first() is not None


def registrar_download(user, versao_id):
    """Registra o download de uma versão por um cliente (sem ciclo)."""
    if cliente_ja_baixou(user, versao_id):
        return False
    novo_download = DownloadControle(
        user_id=user.id,
        versao_id=versao_id,
        data_download=datetime.now(tz_br)
    )
    db.session.add(novo_download)
    db.session.commit()
    return True


def historico_downloads_cliente(user):
    """Retorna lista de versões que o cliente já baixou."""
    downloads = DownloadControle.query.filter_by(user_id=user.id)\
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


def liberado_para_download(user, versao_obj):
    """Verifica se o cliente pode baixar a versão atual (regra antiga, para compatibilidade)."""
    if not versao_obj:
        return False, "Nenhuma versão do robô disponível no momento."
    if getattr(user, 'robot_acesso_bloqueado', False):
        return False, "Seu acesso ao robô está bloqueado. Entre em contato com o suporte."
    if cliente_ja_baixou(user, versao_obj.id):
        return False, "Você já baixou esta versão do robô. Aguarde a próxima atualização."
    return True, "Download liberado."


# ========== NOVAS FUNÇÕES PARA MÚLTIPLOS ROBÔS ==========

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


def ultimo_download_por_produto(user, produto_id):
    """
    Retorna o último registro de DownloadControle para um produto específico (ou None).
    """
    return DownloadControle.query.join(VersaoRobo).filter(
        DownloadControle.user_id == user.id,
        VersaoRobo.produto_id == produto_id
    ).order_by(DownloadControle.data_download.desc()).first()


def cliente_baixou_algum_produto_no_ciclo(user, ciclo_inicio):
    """
    Retorna o produto_id do primeiro download feito no ciclo (ou None).
    """
    download = DownloadControle.query.join(VersaoRobo).filter(
        DownloadControle.user_id == user.id,
        DownloadControle.ciclo_inicio == ciclo_inicio
    ).first()
    if download:
        return download.versao.produto_id
    return None


def liberado_para_download_produto(user, produto_id, ciclo_inicio):
    """
    Verifica se o cliente pode baixar um determinado produto no ciclo atual.
    NÃO exige licença ativa.
    Retorna (bool, mensagem, versao_obj)
    """
    # Bloqueio administrativo geral
    if getattr(user, 'robot_acesso_bloqueado', False):
        return False, "Acesso ao robô bloqueado pelo administrador.", None

    # Versão publicada do produto?
    versao = VersaoRobo.query.filter_by(produto_id=produto_id, publicada=True).first()
    if not versao:
        return False, "Robô indisponível no momento.", None

    # Verifica se já baixou algum produto neste ciclo
    produto_baixado = cliente_baixou_algum_produto_no_ciclo(user, ciclo_inicio)

    if produto_baixado is None:
        # Nenhum download neste ciclo → liberado
        return True, "", versao
    else:
        if produto_baixado == produto_id:
            # Já baixou este produto no ciclo: só libera se houve atualização
            ultimo = ultimo_download_por_produto(user, produto_id)
            if ultimo and ultimo.versao_id != versao.id:
                return True, "", versao
            else:
                return False, "Você já baixou este robô e ele não foi atualizado.", None
        else:
            # Baixou outro produto → bloqueado até próximo ciclo
            return False, "Você já baixou outro robô neste ciclo. Aguarde a próxima semana.", None


def registrar_download_produto(user, versao_obj, ciclo_inicio):
    """
    Registra o download de uma versão de um produto, vinculando ao ciclo.
    Impede duplicatas no mesmo ciclo (idempotente).
    """
    # Verifica se já existe um registro exatamente igual (mesmo ciclo e versão)
    existente = DownloadControle.query.filter_by(
        user_id=user.id,
        versao_id=versao_obj.id,
        ciclo_inicio=ciclo_inicio
    ).first()
    if existente:
        # Já registrado, não faz nada
        return

    novo = DownloadControle(
        user_id=user.id,
        versao_id=versao_obj.id,
        data_download=datetime.now(tz_br),
        ciclo_inicio=ciclo_inicio
    )
    db.session.add(novo)
    db.session.commit()


def obter_produto_baixado_no_ciclo_atual(user):
    """
    Retorna o ID do produto (robô) que o cliente baixou no ciclo atual.
    Utilizado para forçar a geração de licença apenas para o robô já baixado.
    Se nenhum download no ciclo atual, retorna None.
    """
    ciclo_inicio, _ = calcular_ciclo_por_data()
    download = DownloadControle.query.join(VersaoRobo).filter(
        DownloadControle.user_id == user.id,
        DownloadControle.ciclo_inicio == ciclo_inicio
    ).first()
    if download:
        return download.versao.produto_id
    return None