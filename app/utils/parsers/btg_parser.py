import re
from pypdf import PdfReader

def extrair_dados_btg(caminho_arquivo):
    print(f"\n==================================================")
    print(f"[BTG_PARSER] INICIANDO ROBÔ BTG (POSIÇÃO + LETRA)")
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
            print(f"\n  [BUSCA] Analisando Campo: '{nome_campo}'")
            print(f"  [BUSCA] Padrão (Regex): '{padrao}' | Posição-Alvo: {posicao}")
            
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                # Pega um bloco maior (300 caracteres) após a palavra-chave
                bloco_depois = texto[match.end():match.end()+300]
                print(f"    -> [TEXTO CRU LIDO LOGO APÓS A PALAVRA]:")
                print(f"       {repr(bloco_depois[:100])}...")
                
                # LIMPEZA DO CAOS DO BTG ANTES DE PROCURAR OS NÚMEROS:
                # 1. Troca a barra vertical '|' por um espaço para não ser lida como o número '1'
                bloco_limpo = bloco_depois.replace('|', ' ')
                
                # 2. Arruma letras grudadas nos números (ex: 123,00D vira 123,00 D)
                bloco_limpo = re.sub(r'(,\d{2})([CDcd])\b', r'\1 \2', bloco_limpo)
                
                print(f"    -> [TEXTO LIMPO (Sem '|' e separado)]:")
                print(f"       {repr(bloco_limpo[:100])}...")

                # 3. A REGEX PREDADORA: Procura o número e Opcionalmente o C ou D logo na frente
                regex_numeros = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s*([CDcd])?"
                matches = re.findall(regex_numeros, bloco_limpo)
                
                print(f"    -> Valores e Letras localizados na ordem em que aparecem:")
                for i, m in enumerate(matches):
                    print(f"       [{i+1}] {m[0]} {m[1]}")
                
                if matches and len(matches) >= posicao:
                    valor_str, letra = matches[posicao - 1]
                    
                    # Converte para float matemático
                    num_str = valor_str.replace('.', '').replace(',', '.')
                    num = float(num_str)
                    
                    if aceita_cd:
                        if letra and letra.upper() == 'D':
                            num = -num
                            print(f"    -> [SUCESSO] Letra 'D' aplicada. Retornando LOSS (Negativo): {num}")
                        elif letra and letra.upper() == 'C':
                            print(f"    -> [SUCESSO] Letra 'C' aplicada. Retornando GAIN (Positivo): {num}")
                        else:
                            print(f"    -> [SUCESSO] Nenhuma letra detectada. Retornando Positivo: {num}")
                    else:
                        num = abs(num) 
                        print(f"    -> [SUCESSO] Campo de Despesa/Taxa. Forçado Absoluto: {num}")
                        
                    return num
                else:
                    print(f"    -> [ERRO] O PDF só tem {len(matches)} valores, mas você pediu a posição {posicao}.")
            else:
                print(f"    -> [ERRO] A palavra-chave '{padrao}' sumiu do PDF.")
            return 0.0

        # --- EXTRAÇÃO DE DADOS POR POSIÇÃO NO BTG ---
        # No BTG (BM&F), o Bruto não fica no "Valor dos negócios". Fica no "Ajuste day trade".
        # Vamos testar olhar para a palavra 'Ajuste day trade' e pegar a posição 1.
        v_bruto = extrair_por_posicao("Valor Bruto (Ajuste Day Trade)", r"Ajuste day trade", texto_completo, 1, aceita_cd=True)
        
        # O IRRF 1% no BTG fica depois de 'IRRF Day Trade (proj.)'. A posição varia, vamos testar a 2.
        v_irrf_1 = extrair_por_posicao("IRRF Day Trade (1%)", r"IRRF Day Trade \(proj\.\)", texto_completo, 2, aceita_cd=False)
        
        # Total das Despesas
        v_taxas_b3 = extrair_por_posicao("Taxas B3", r"Total das despesas", texto_completo, 1, aceita_cd=False)

        print("\n  [MATEMÁTICA] --- INICIANDO CÁLCULOS DO PREGÃO ---")
        
        print(f"    Fórmula: Líquido Pregão = Bruto ({v_bruto}) - Taxas B3 ({v_taxas_b3}) - IRRF 1% ({v_irrf_1})")
        v_liquido_pregao = round(v_bruto - v_taxas_b3 - v_irrf_1, 2)
        print(f"    Resultado Líquido Pregão: {v_liquido_pregao}")
        
        if v_liquido_pregao > 0:
            v_irrf_19 = round(v_liquido_pregao * 0.19, 2)
            print(f"    Fórmula: IRRF 19% = {v_liquido_pregao} * 0.19 = {v_irrf_19}")
        else:
            v_irrf_19 = 0.0
            print(f"    Fórmula: IRRF 19% = 0.00 (Pregão foi LOSS ou Zero)")
            
        v_liquido_dia = round(v_liquido_pregao - v_irrf_19, 2)
        print(f"    Fórmula: Líquido do Dia = {v_liquido_pregao} - {v_irrf_19} = {v_liquido_dia}")
        
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

