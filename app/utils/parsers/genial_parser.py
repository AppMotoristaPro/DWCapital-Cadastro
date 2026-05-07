import re
from pypdf import PdfReader

def extrair_dados_genial(caminho_arquivo):
    print(f"[GENIAL_PARSER] Iniciando robô Genial. Arquivo: {caminho_arquivo}")
    try:
        leitor = PdfReader(caminho_arquivo)
        ultima_pagina = leitor.pages[-1]
        texto_completo = ultima_pagina.extract_text()
        print("[GENIAL_PARSER] Texto lido.")
        
        if "GENIAL" not in texto_completo.upper():
            print("[GENIAL_PARSER] ERRO: O PDF não pertence à Genial Investimentos.")
            return None
        
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo)
        data_pregao = match_data.group(1) if match_data else None

        def limpar_valor(resultado, letra):
            if not resultado: return 0.0
            resultado = re.sub(r'[^\d,.]', '', resultado)
            if ',' in resultado:
                val = resultado.replace('.', '').replace(',', '.')
            else:
                val = resultado
            try:
                num = float(val)
                # SE TIVER A LETRA D (DÉBITO), TRANSFORMA EM NEGATIVO (LOSS)
                if letra and letra.upper() == 'D':
                    num = num * -1
                return num
            except:
                return 0.0

        def extrair_por_posicao(padrao, texto, posicao):
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                bloco_depois = texto[match.end():match.end()+200]
                # A Regex agora captura o número e a letra C ou D que estiver na frente
                numeros = re.findall(r"(\d[\d\.,]*[\.,]\d{2})\s*([DCdc]?)", bloco_depois)
                if numeros and len(numeros) >= posicao:
                    return limpar_valor(numeros[posicao - 1][0], numeros[posicao - 1][1])
            return 0.0

        v_bruto = extrair_por_posicao(r"Valor dos negócios", texto_completo, 1)
        v_irrf_1 = extrair_por_posicao(r"IRRF Day Trade", texto_completo, 2)
        v_taxas_b3 = extrair_por_posicao(r"Total das despesas", texto_completo, 4)

        v_liquido_pregao = v_bruto - v_taxas_b3 - v_irrf_1
        v_irrf_19 = v_liquido_pregao * 0.19 if v_liquido_pregao > 0 else 0.0
        v_liquido_dia = v_liquido_pregao - v_irrf_19
        
        # O REPASSE ZERA AUTOMATICAMENTE SE FOR LOSS
        v_repasse = v_liquido_dia * 0.30 if v_liquido_dia > 0 else 0.0
        
        print(f"[GENIAL_PARSER] Valores extraídos: {v_bruto} / {v_taxas_b3}")

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
        print(f"[GENIAL_PARSER] Erro: {str(e)}")
        return None

