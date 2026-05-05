import re
from pypdf import PdfReader

def extrair_dados_nota_corretagem(caminho_arquivo):
    try:
        leitor = PdfReader(caminho_arquivo)
        
        # Extrai a Data do Pregão
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

        # 1. Extração do Valor Líquido do Pregão (Líquido da Nota)
        v_liquido_pregao = 0.0
        match_liquido = re.findall(r"(\d[\d\.,]+\d{2})\s*$", texto_completo, re.MULTILINE)
        if match_liquido:
            v_liquido_pregao = limpar_valor(match_liquido[-1])

        # Extração do IRRF (Dedo Duro 1%) e Taxas da B3
        match_resumo = re.search(r"IRRF Day Trade.*?([\d\.,]+\d{2})\s+D\s+0,00\s+([\d\.,]+\d{2})\s+([\d\.,]+\d{2})", texto_completo, re.DOTALL)
        
        v_irrf_1 = 0.0
        v_taxas_b3 = 0.0
        if match_resumo:
            v_irrf_1 = limpar_valor(match_resumo.group(1))
            v_taxas_b3 = limpar_valor(match_resumo.group(2)) + limpar_valor(match_resumo.group(3))

        # --- CÁLCULOS DW CAPITAL ---

        # Valor Bruto
        v_bruto = v_liquido_pregao + v_irrf_1 + v_taxas_b3

        # Base do IR 19% e Valor do DARF
        base_calculo_ir = v_bruto - v_taxas_b3
        v_irrf_19 = base_calculo_ir * 0.19 if base_calculo_ir > 0 else 0.0
        
        # Valor Líquido do Cliente (Dia)
        v_liquido_dia = v_liquido_pregao - v_irrf_19

        # Repasse DW Capital (30%)
        v_repasse = v_liquido_dia * 0.30 if v_liquido_dia > 0 else 0.0

        return {
            'data_pregao': data_pregao,
            'bruto': v_bruto,
            'taxas_b3': v_taxas_b3,
            'irrf_1': v_irrf_1,
            'liquido_pregao': v_liquido_pregao,
            'irrf_19': v_irrf_19,
            'liquido_dia': v_liquido_dia,
            'repasse_dw': v_repasse
        }

    except Exception as e:
        print(f"Erro no Parser: {e}")
        return None

