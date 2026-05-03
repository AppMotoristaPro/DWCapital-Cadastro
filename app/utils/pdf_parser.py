import re
from pypdf import PdfReader

def extrair_dados_nota_corretagem(caminho_arquivo):
    try:
        leitor = PdfReader(caminho_arquivo)
        texto_completo = ""
        
        # Junta o texto de todas as páginas
        for pagina in leitor.pages:
            texto_extraido = pagina.extract_text()
            if texto_extraido:
                texto_completo += texto_extraido + "\n"

        # Regex para caçar os valores no formato "1.571,00 C" ou "88,00 D"
        # O re.DOTALL permite que a busca ignore quebras de linha entre o título e o valor
        padrao_bruto = r"Ajuste day trade.*?([\d\.]+,\d{2})\s*([CD])"
        padrao_liquido = r"Total l[ií]quido da nota.*?([\d\.]+,\d{2})\s*([CD])"

        busca_bruto = re.search(padrao_bruto, texto_completo, re.IGNORECASE | re.DOTALL)
        busca_liquido = re.search(padrao_liquido, texto_completo, re.IGNORECASE | re.DOTALL)

        def converter_para_float(match):
            if not match:
                return 0.0
            
            valor_str = match.group(1) # Pega "1.468,17"
            tipo = match.group(2).upper() # Pega "C" ou "D"
            
            # Remove o ponto de milhar e troca vírgula por ponto
            valor_float = float(valor_str.replace('.', '').replace(',', '.'))
            
            # Se for Débito (Prejuízo), o valor fica negativo
            if tipo == 'D':
                valor_float = -valor_float
                
            return valor_float

        faturamento_bruto = converter_para_float(busca_bruto)
        faturamento_liquido = converter_para_float(busca_liquido)

        return faturamento_bruto, faturamento_liquido

    except Exception as e:
        print(f"Erro ao processar PDF: {e}")
        return None, None

