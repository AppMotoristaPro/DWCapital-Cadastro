import re
from pypdf import PdfReader

def extrair_dados_nota_corretagem(caminho_arquivo):
    try:
        leitor = PdfReader(caminho_arquivo)
        
        # Extrai a Data do Pregão da primeira página
        texto_primeira_pagina = leitor.pages[0].extract_text()
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_primeira_pagina)
        data_pregao = match_data.group(1) if match_data else None

        # Extrai valores financeiros das páginas finais
        texto_completo = ""
        paginas_finais = leitor.pages[-2:] if len(leitor.pages) > 1 else leitor.pages
        for pagina in paginas_finais:
            texto_completo += pagina.extract_text() + "\n"

        def limpar_valor(resultado):
            if not resultado: return 0.0
            val = resultado.replace('.', '').replace(',', '.')
            return float(val)

        v_liquido = 0.0
        match_liquido = re.findall(r"(\d[\d\.,]+\d{2})\s*$", texto_completo, re.MULTILINE)
        if match_liquido:
            v_liquido = limpar_valor(match_liquido[-1])

        match_resumo = re.search(r"IRRF Day Trade.*?([\d\.,]+\d{2})\s+D\s+0,00\s+([\d\.,]+\d{2})\s+([\d\.,]+\d{2})", texto_completo, re.DOTALL)
        
        v_irrf = 0.0
        v_taxas = 0.0
        if match_resumo:
            v_irrf = limpar_valor(match_resumo.group(1))
            v_taxas = limpar_valor(match_resumo.group(2)) + limpar_valor(match_resumo.group(3))

        v_bruto = v_liquido + v_irrf + v_taxas

        return {
            'data_pregao': data_pregao,
            'bruto': v_bruto,
            'liquido': v_liquido,
            'irrf_1': v_irrf,
            'taxas_b3': v_taxas
        }

    except Exception as e:
        print(f"Erro no Parser: {e}")
        return None

