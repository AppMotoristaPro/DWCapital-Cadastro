from .genial_parser import extrair_dados_genial
from .xp_parser import extrair_dados_xp
# from .btg_parser import extrair_dados_btg # Deixado pronto para o futuro

def processar_pdf(caminho_arquivo, corretora, cpf_cliente):
    """
    Recebe o PDF, a corretora alvo e o CPF do cliente.
    Direciona o arquivo para o robô especialista correto.
    """
    corretora = corretora.upper()
    
    if corretora == 'GENIAL':
        return extrair_dados_genial(caminho_arquivo)
        
    elif corretora == 'XP':
        return extrair_dados_xp(caminho_arquivo, cpf_cliente)
        
    elif corretora == 'BTG':
        # return extrair_dados_btg(caminho_arquivo)
        pass
        
    else:
        raise Exception(f"Corretora {corretora} não possui um robô de leitura configurado.")

