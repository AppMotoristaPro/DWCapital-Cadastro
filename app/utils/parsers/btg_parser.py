import re
from pypdf import PdfReader

def extrair_dados_btg(caminho_arquivo):
    print(f"\n==================================================")
    print(f"[BTG_PARSER] INICIANDO ROBÔ SNIPER BTG")
    print(f"==================================================")
    print(f"[BTG_PARSER] Arquivo alvo: {caminho_arquivo}")
    try:
        leitor = PdfReader(caminho_arquivo)
        ultima_pagina = leitor.pages[-1]
        texto_completo = ultima_pagina.extract_text()
        print("[BTG_PARSER] Texto lido com sucesso.")
        
        if "BTG PACTUAL" not in texto_completo.upper():
            return None
        
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo)
        data_pregao = match_data.group(1) if match_data else None

        # PREPARAÇÃO DO RESUMO (Limpeza do BTG e Pipes)
        resumo = texto_completo[-2000:]
        resumo_limpo = re.sub(r'[\n\r\|]', ' ', resumo)
        resumo_limpo = re.sub(r'1\s+D\b', ' D', resumo_limpo, flags=re.IGNORECASE)
        resumo_limpo = re.sub(r'1\s+C\b', ' C', resumo_limpo, flags=re.IGNORECASE)

        # 1. Busca todos os valores com C/D
        matches_cd = re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*([CDcd])\b", resumo_limpo)
        validos_cd = [(val, letra) for val, letra in matches_cd if val != '0,00']
        
        v_bruto = 0.0
        v_total_liquido = 0.0
        
        if validos_cd:
            # Primeiro valor com C/D
            val_b, let_b = validos_cd[0]
            v_bruto = float(val_b.replace('.', '').replace(',', '.'))
            if let_b.upper() == 'D': v_bruto = -v_bruto
            
            # Último valor com C/D
            val_l, let_l = validos_cd[-1]
            v_total_liquido = float(val_l.replace('.', '').replace(',', '.'))
            if let_l.upper() == 'D': v_total_liquido = -v_total_liquido

        # 2. Busca do IRRF (O BTG amassa o número ANTES da palavra IRRF)
        v_irrf_1 = 0.0
        match_irrf = re.search(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*IRRF Day Trade", resumo_limpo, re.IGNORECASE)
        if match_irrf:
            v_irrf_1 = float(match_irrf.group(1).replace('.', '').replace(',', '.'))

        # 3. DEDUÇÃO MATEMÁTICA DAS TAXAS B3
        v_taxas_b3 = round(abs(v_bruto - v_total_liquido) - v_irrf_1, 2)
        v_taxas_b3 = max(0.0, v_taxas_b3)

        print(f"\n  [SNIPER] MATEMÁTICA DEDUTIVA B3:")
        print(f"    -> Bruto Encontrado: {v_bruto}")
        print(f"    -> Total Líquido Encontrado: {v_total_liquido}")
        print(f"    -> IRRF 1% Encontrado: {v_irrf_1}")
        print(f"    -> Taxas B3 Deduzidas: |({v_bruto}) - ({v_total_liquido})| - {v_irrf_1} = {v_taxas_b3}")

        # REPASSE ZERO NO LOSS
        v_liquido_pregao = v_bruto - v_taxas_b3 - v_irrf_1
        v_irrf_19 = v_liquido_pregao * 0.19 if v_liquido_pregao > 0 else 0.0
        v_liquido_dia = v_liquido_pregao - v_irrf_19
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
        print(f"[BTG_PARSER] Erro crítico: {str(e)}")
        return None

