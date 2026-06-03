# app/utils/validators.py

def validar_cpf(cpf: str) -> bool:
    """
    Valida um número de CPF brasileiro (com ou sem formatação).
    
    Args:
        cpf (str): CPF a ser validado. Pode conter pontos, traços ou apenas números.
    
    Returns:
        bool: True se o CPF for válido, False caso contrário.
    """
    # Remove caracteres não numéricos
    cpf = ''.join(filter(str.isdigit, cpf))
    
    # Verifica se tem 11 dígitos ou se todos são iguais (ex: 111.111.111-11)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    
    # Função interna para calcular o dígito verificador
    def calcular_digito(peso_inicial: int) -> int:
        soma = 0
        for i in range(peso_inicial - 1):
            soma += int(cpf[i]) * (peso_inicial - i)
        resto = soma % 11
        return 0 if resto < 2 else 11 - resto
    
    # Calcula o primeiro e segundo dígito verificador
    digito1 = calcular_digito(10)
    digito2 = calcular_digito(11)
    
    # Compara com os dois últimos dígitos do CPF informado
    return cpf[-2:] == f"{digito1}{digito2}"


# ALTERAÇÃO FASE 3 - Validação de MIME de PDF (assinatura mágica)
def validar_pdf_mime(arquivo):
    """
    Verifica se o arquivo é um PDF válido pela assinatura mágica (%PDF).
    
    Args:
        arquivo: Objeto FileStorage do Flask (request.files['...']).
    
    Returns:
        bool: True se os primeiros 4 bytes forem b'%PDF', False caso contrário.
    """
    # Lê os primeiros 4 bytes do arquivo
    header = arquivo.read(4)
    # Volta o ponteiro para o início
    arquivo.seek(0)
    return header == b'%PDF'
