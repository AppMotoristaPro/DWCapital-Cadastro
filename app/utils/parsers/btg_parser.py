import re
from pypdf import PdfReader

def extrair_dados_btg(caminho_arquivo):
    print(f"\n==================================================")
    print(f"[BTG_PARSER] INICIANDO ROBÔ BTG")
    print(f"==================================================")
    print(f"[BTG_PARSER] Arquivo alvo: {caminho_arquivo}")
    try:
        leitor = PdfReader(caminho_arquivo)
        ultima_pagina = leitor.pages[-1]
        texto_completo = ultima_pagina.extract_text()
        print("[BTG_PARSER] Texto lido com sucesso.")
        
        if "BTG PACTUAL" not in texto_completo.upper():
            print("[BTG_PARSER] ERRO: O PDF não pertence ao BTG Pactual.")
            return None
        
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo)
        data_pregao = match_data.group(1) if match_data else None
        print(f"[BTG_PARSER] Data encontrada: {data_pregao}\n")

        def extrair_por_posicao(nome_campo, padrao, texto, posicao, aceita_cd=False):
            print(f"  [BUSCA] Campo: '{nome_campo}' | Padrão: '{padrao}' | Posição: {posicao}")
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                bloco_depois = texto[match.end():match.end()+200]
                print(f"    -> Bloco extraído: {repr(bloco_depois[:60])}...")
                
                regex_numeros = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s*([CDcd])?"
                matches = re.findall(regex_numeros, bloco_depois)
                
                print(f"    -> Valores localizados: {matches}")
                
                if matches and len(matches) >= posicao:
                    valor_str, letra = matches[posicao - 1]
                    num_str = valor_str.replace('.', '').replace(',', '.')
                    num = float(num_str)
                    
                    if aceita_cd:
                        if letra and letra.upper() == 'D':
                            num = -num
                            print(f"    -> [!] Letra 'D' detectada. Convertido para LOSS (Negativo): {num}")
                        elif letra and letra.upper() == 'C':
                            print(f"    -> [!] Letra 'C' detectada. Mantido como GAIN (Positivo): {num}")
                        else:
                            print(f"    -> [!] Nenhuma letra C/D detectada. Assumindo POSITIVO: {num}")
                    else:
                        num = abs(num) 
                        print(f"    -> [!] Campo de Despesa. Forçado para absoluto POSITIVO: {num}")
                        
                    return num
                else:
                    print(f"    -> [ERRO] Posição {posicao} não existe. Encontrados apenas {len(matches)} itens.")
            else:
                print(f"    -> [ERRO] Padrão não encontrado no PDF.")
            return 0.0

        # --- EXTRAÇÃO DE DADOS ---
        v_bruto = extrair_por_posicao("Valor Bruto", r"Valor dos negócios", texto_completo, 1, aceita_cd=True)
        v_irrf_1 = extrair_por_posicao("IRRF Day Trade (1%)", r"IRRF Day Trade", texto_completo, 2, aceita_cd=False)
        v_taxas_b3 = extrair_por_posicao("Taxas B3", r"Total das despesas", texto_completo, 4, aceita_cd=False)

        print("\n  [MATEMÁTICA] --- INICIANDO CÁLCULOS DO PREGÃO ---")
        
        # Líquido do Pregão
        print(f"    Fórmula: Líquido Pregão = Bruto ({v_bruto}) - Taxas B3 ({v_taxas_b3}) - IRRF 1% ({v_irrf_1})")
        v_liquido_pregao = v_bruto - v_taxas_b3 - v_irrf_1
        print(f"    Resultado Líquido Pregão: {v_liquido_pregao}")
        
        # IRRF 19%
        if v_liquido_pregao > 0:
            v_irrf_19 = v_liquido_pregao * 0.19
            print(f"    Fórmula: IRRF 19% = {v_liquido_pregao} * 0.19 = {v_irrf_19}")
        else:
            v_irrf_19 = 0.0
            print(f"    Fórmula: IRRF 19% = 0.00 (Pregão foi LOSS)")
            
        # Líquido do Dia
        v_liquido_dia = v_liquido_pregao - v_irrf_19
        print(f"    Fórmula: Líquido do Dia = {v_liquido_pregao} - {v_irrf_19} = {v_liquido_dia}")
        
        # Repasse DW
        if v_liquido_dia > 0:
            v_repasse = v_liquido_dia * 0.30
            print(f"    Fórmula: Repasse DW = {v_liquido_dia} * 0.30 = {v_repasse}")
        else:
            v_repasse = 0.0
            print(f"    Fórmula: Repasse DW = 0.00 (Sem repasse no Loss)")

        print("  [MATEMÁTICA] --- FIM DOS CÁLCULOS ---\n")

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

