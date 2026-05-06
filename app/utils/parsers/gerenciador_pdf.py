from .genial_parser import extrair_dados_genial
from .xp_parser import extrair_dados_xp
from .btg_parser import extrair_dados_btg

def processar_pdf(caminho_arquivo, corretora, cpf_cliente, senha_manual=None):
    corretora = corretora.upper()
    
    if corretora == 'GENIAL':
        return extrair_dados_genial(caminho_arquivo)
        
    elif corretora == 'XP':
        return extrair_dados_xp(caminho_arquivo, cpf_cliente, senha_manual)
        
    elif corretora == 'BTG':
        return extrair_dados_btg(caminho_arquivo)
        
    else:
        raise Exception(f"Corretora {corretora} não configurada.")

