from .genial_parser import extrair_dados_genial
from .xp_parser import extrair_dados_xp
from .btg_parser import extrair_dados_btg

def processar_pdf(caminho_arquivo, corretora, cpf_cliente, senha_manual=None):
    corretora = corretora.upper()
    print(f"\n[GERENCIADOR] Iniciando processamento. Corretora alvo: {corretora}")
    
    if corretora == 'GENIAL':
        return extrair_dados_genial(caminho_arquivo)
        
    elif corretora == 'XP':
        return extrair_dados_xp(caminho_arquivo, cpf_cliente, senha_manual)
        
    elif corretora == 'BTG':
        return extrair_dados_btg(caminho_arquivo)
        
    else:
        print(f"[GERENCIADOR] ERRO: Corretora {corretora} não está configurada.")
        raise Exception(f"Corretora {corretora} não configurada.")

