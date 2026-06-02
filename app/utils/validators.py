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
