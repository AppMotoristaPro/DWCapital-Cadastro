"""
Serviço para controle de versão do robô e downloads.
Gerencia a versão ativa, o histórico de downloads por cliente e o bloqueio de múltiplos downloads.
"""

from datetime import datetime
import pytz
from app import db
from app.models import VersaoRobo, DownloadControle

tz_br = pytz.timezone('America/Sao_Paulo')

def versao_atual():
    """Retorna o objeto VersaoRobo que está com publicada=True, ou None."""
    return VersaoRobo.query.filter_by(publicada=True).first()

def cliente_ja_baixou(user, versao_id):
    """Verifica se o cliente já baixou uma determinada versão do robô."""
    return DownloadControle.query.filter_by(user_id=user.id, versao_id=versao_id).first() is not None

def registrar_download(user, versao_id):
    """
    Registra o download de uma versão por um cliente.
    Retorna True se o registro foi criado, False se já existia.
    """
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
    """
    Retorna uma lista de dicionários com as versões que o cliente já baixou,
    ordenadas da mais recente para a mais antiga.
    """
    downloads = DownloadControle.query.filter_by(user_id=user.id)\
        .join(VersaoRobo)\
        .order_by(DownloadControle.data_download.desc()).all()
    historico = []
    for d in downloads:
        historico.append({
            'versao': d.versao.versao,
            'data_download': d.data_download,
            'novidades': d.versao.novidades  # útil se quiser mostrar
        })
    return historico

def liberado_para_download(user, versao_obj):
    """Verifica se o cliente pode baixar a versão atual (regra: apenas se ainda não baixou)."""
    if not versao_obj:
        return False, "Nenhuma versão do robô disponível no momento."
    if cliente_ja_baixou(user, versao_obj.id):
        return False, "Você já baixou esta versão do robô. Aguarde a próxima atualização."
    return True, "Download liberado."
