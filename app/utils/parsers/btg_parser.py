import re
from pypdf import PdfReader

def extrair_dados_btg(caminho_arquivo):
    print(f"\n==================================================")
    print(f"[BTG_PARSER] INICIANDO ROBÔ BTG (ENGENHARIA REVERSA UNIFICADA)")
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

        def extrair_por_posicao(nome_campo, padrao, texto, posicao, aceita_cd=False, janela_tras=0, janela_frente=200):
            print(f"\n  [BUSCA] Analisando Campo: '{nome_campo}'")
            print(f"  [BUSCA] Padrão (Regex): '{padrao}' | Direção: Para trás")
            
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                inicio = max(0, match.start() - janela_tras)
                fim = min(len(texto), match.end() + janela_frente)
                bloco = texto[inicio:fim]
                
                bloco_limpo = bloco.replace('|', ' ')
                bloco_limpo = re.sub(r'\b1\s+D\b', ' D', bloco_limpo, flags=re.IGNORECASE)
                bloco_limpo = re.sub(r'\b1\s+C\b', ' C', bloco_limpo, flags=re.IGNORECASE)
                bloco_limpo = re.sub(r'(,\d{2})1\s*([CDcd])\b', r'\1 \2', bloco_limpo)
                bloco_limpo = re.sub(r'(,\d{2})\s*([CDcd])\b', r'\1 \2', bloco_limpo)
                
                regex_numeros = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s*([CDcd])?"
                matches = re.findall(regex_numeros, bloco_limpo)
                
                if matches:
                    try:
                        alvo = matches[posicao - 1] if posicao > 0 else matches[posicao] 
                        valor_str, letra = alvo
                        num = float(valor_str.replace('.', '').replace(',', '.'))
                        
                        if aceita_cd:
                            if letra and letra.upper() == 'D':
                                num = -num
                                print(f"    -> [SUCESSO] Letra 'D' aplicada. Retornando LOSS (Negativo): {num}")
                            elif letra and letra.upper() == 'C':
                                print(f"    -> [SUCESSO] Letra 'C' aplicada. Retornando GAIN (Positivo): {num}")
                            else:
                                print(f"    -> [SUCESSO] Nenhuma letra C/D. Assumindo Positivo: {num}")
                        else:
                            num = abs(num) 
                            print(f"    -> [SUCESSO] Campo de Despesa/Taxa. Forçado Absoluto: {num}")
                            
                        return num
                    except IndexError:
                        print(f"    -> [ERRO] A posição não existe.")
                else:
                    print(f"    -> [ERRO] Nenhum número encontrado na janela.")
            else:
                print(f"    -> [ERRO] A âncora '{padrao}' sumiu do PDF.")
            return 0.0

        # --- ENGENHARIA REVERSA ---
        # 1. Pega o Líquido da Nota olhando estritamente para TRÁS da frase "Custos BM&F" (garante a captura do sinal C/D)
        v_liquido_pregao = extrair_por_posicao("Líquido da Nota", r"Custos BM&F", texto_completo, -1, aceita_cd=True, janela_tras=100, janela_frente=0)
        
        # 2. Pega as Taxas olhando para TRÁS da frase "Total das despesas"
        v_taxas_b3 = extrair_por_posicao("Taxas B3", r"Total das despesas", texto_completo, -1, aceita_cd=False, janela_tras=40, janela_frente=0)
        
        # 3. Pega o IR olhando para TRÁS da frase "IRRF Day Trade"
        v_irrf_1 = extrair_por_posicao("IRRF Day Trade 1%", r"IRRF Day Trade", texto_completo, -1, aceita_cd=False, janela_tras=40, janela_frente=0)

        print("\n  [MATEMÁTICA] --- INICIANDO CÁLCULOS DO PREGÃO ---")
        
        v_custos_unificados = round(v_taxas_b3 + v_irrf_1, 2)
        
        # O Bruto é reconstruído matematicamente: Líquido + Custos
        v_bruto = round(v_liquido_pregao + v_custos_unificados, 2)
        
        print(f"    Custos Unificados Extraídos: {v_custos_unificados}")
        print(f"    Bruto Reconstruído: Líquido ({v_liquido_pregao}) + Custos ({v_custos_unificados}) = {v_bruto}")

        if v_liquido_pregao > 0:
            v_irrf_19 = round(v_liquido_pregao * 0.19, 2)
            print(f"    Fórmula: IRRF 19% = {v_liquido_pregao} * 0.19 = {v_irrf_19}")
        else:
            v_irrf_19 = 0.0
            print(f"    Fórmula: IRRF 19% = 0.00 (Pregão foi LOSS ou Zero)")
            
        v_liquido_dia = round(v_liquido_pregao - v_irrf_19, 2)
        print(f"    Fórmula: Líquido Real = {v_liquido_pregao} - {v_irrf_19} = {v_liquido_dia}")
        
        if v_liquido_dia > 0:
            v_repasse = round(v_liquido_dia * 0.30, 2)
            print(f"    Fórmula: Repasse DW = {v_liquido_dia} * 0.30 = {v_repasse}")
        else:
            v_repasse = 0.0
            print(f"    Fórmula: Repasse DW = 0.00 (Sem repasse no Loss)")

        print("  [MATEMÁTICA] --- FIM DOS CÁLCULOS ---\n")

        return {
            'data_pregao': data_pregao,
            'bruto': v_bruto,
            'taxas_b3': v_custos_unificados,
            'irrf_1': 0.0,  # Fica zerado no BD pois já está dentro de taxas_b3 (Unificado)
            'liquido_pregao': v_liquido_pregao,
            'irrf_19': v_irrf_19,
            'liquido_dia': v_liquido_dia,
            'repasse_dw': v_repasse
        }
    except Exception as e:
        print(f"[BTG_PARSER] Erro crítico: {str(e)}")
        return None

