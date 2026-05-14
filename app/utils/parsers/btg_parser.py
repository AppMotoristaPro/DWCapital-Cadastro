import re
from pypdf import PdfReader

def extrair_dados_btg(caminho_arquivo):
    print(f"\n" + "="*50)
    print(f"[BTG_PARSER] INICIANDO ROBÔ BTG V2 (BLINDAGEM TOTAL E LOGS)")
    print(f"="*50)
    print(f"[BTG_PARSER] Arquivo alvo: {caminho_arquivo}")
    try:
        leitor = PdfReader(caminho_arquivo)
        ultima_pagina = leitor.pages[-1]
        texto_original = ultima_pagina.extract_text()
        print("[BTG_PARSER] Texto lido com sucesso. Iniciando sanitização...")
        
        if "BTG PACTUAL" not in texto_original.upper():
            print("[BTG_PARSER] ERRO: O PDF não pertence ao BTG Pactual.")
            return None
        
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_original)
        data_pregao = match_data.group(1) if match_data else None
        print(f"[BTG_PARSER] Data encontrada: {data_pregao}\n")

        # ==================================================
        # SANITIZAÇÃO DO TEXTO (REMOVENDO FANTASMAS DA BTG)
        # ==================================================
        texto_limpo = texto_original
        
        # 1. Conserta formatação corrompida de milhares (ex: 1.035.451 C -> 1.035,451 C)
        texto_limpo = re.sub(r'(\d)\.(\d{2})([1Iil\|]*\s*[CDcd])\b', r'\1,\2\3', texto_limpo)
        
        # 2. Remove o fantasma '1' ou 'I' se vier acompanhado de letra C/D (ex: 1.035,451 C -> 1.035,45 C)
        texto_limpo = re.sub(r'(,\d{2})\s*[1Iil\|]+\s*([CDcd])\b', r'\1 \2', texto_limpo)
        
        # 3. Remove o fantasma '1' ou 'I' se for um número solto (ex: 0,001 -> 0,00)
        texto_limpo = re.sub(r'(,\d{2})\s*[1Iil\|]+\b', r'\1', texto_limpo)

        # Imprime o terço final do documento para você enxergar no Log do Render
        print(f"  [DUMP DO RESUMO FINANCEIRO SANITIZADO]")
        trecho_resumo = texto_limpo[-1200:]
        for linha in trecho_resumo.split('\n'):
            if linha.strip(): print(f"    | {linha.strip()}")
        print(f"  [FIM DO DUMP]\n")

        # ==================================================
        # 1. EXTRAÇÃO DO LÍQUIDO DA NOTA
        # Na BTG, o "Total líquido da nota" é SEMPRE o último valor com C ou D no rodapé
        # ==================================================
        print("  [BUSCA] Procurando Líquido da Nota (Último valor C/D)")
        valores_finais = re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*([CDcd])\b", trecho_resumo)
        if not valores_finais:
            raise Exception("Nenhum valor financeiro encontrado no rodapé sanitizado.")
        
        ultimo_valor, ultima_letra = valores_finais[-1]
        v_liquido_pregao = float(ultimo_valor.replace('.', '').replace(',', '.'))
        if ultima_letra.upper() == 'D':
            v_liquido_pregao = -v_liquido_pregao
            
        print(f"    -> [SUCESSO] Líquido Extraído: {v_liquido_pregao}")

        # ==================================================
        # 2. EXTRAÇÃO DO BRUTO (Ajuste Day Trade)
        # ==================================================
        print("\n  [BUSCA] Procurando Bloco de Operações ('Total das despesas')")
        
        # A BTG sempre empilha: Ajuste de Posição (0,00) + Ajuste Day Trade (Bruto) + Total das Despesas (Custos)
        regex_bloco = r"Total das despesas\s+([\d.,]+)\s*([CDcd])?\s+([\d.,]+)\s*([CDcd])\s+([\d.,]+)\s*([CDcd])"
        match_bloco = re.search(regex_bloco, texto_limpo, re.IGNORECASE)
        
        if match_bloco:
            _, _, val_dt, cd_dt, _, _ = match_bloco.groups()
            
            v_bruto = float(val_dt.replace('.', '').replace(',', '.'))
            if cd_dt and cd_dt.upper() == 'D':
                v_bruto = -v_bruto
            print(f"    -> [SUCESSO] Bruto (Ajuste Day Trade): {v_bruto}")
        else:
            # Fallback se o cliente não tiver "Ajuste de posição" na nota (Apenas 2 números)
            regex_bloco_2 = r"Total das despesas\s+([\d.,]+)\s*([CDcd])\s+([\d.,]+)\s*([CDcd])"
            match_bloco_2 = re.search(regex_bloco_2, texto_limpo, re.IGNORECASE)
            if match_bloco_2:
                val_dt, cd_dt, _, _ = match_bloco_2.groups()
                v_bruto = float(val_dt.replace('.', '').replace(',', '.'))
                if cd_dt and cd_dt.upper() == 'D': v_bruto = -v_bruto
                print(f"    -> [SUCESSO] Bruto: {v_bruto} (Fallback)")
            else:
                raise Exception("Falha grave: O bloco 'Total das despesas' e 'Ajuste day trade' sumiu ou mudou de lugar.")

        # ==================================================
        # 3. VACINA MATEMÁTICA E CÁLCULOS FINAIS
        # ==================================================
        print("\n  [MATEMÁTICA] --- INICIANDO CÁLCULOS DO PREGÃO ---")
        
        # Usa a mesma vacina da Genial: Bruto - Líquido engole B3 + IRRF perfeitamente
        v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
        
        # Tratamento para notas que dão loss e invertem a lógica matemática do PDF
        if v_custos_unificados < 0:
            print(f"    [!] Anomalia BTG: Custos negativos detectados ({v_custos_unificados}). O PDF ocultou o sinal de Loss!")
            v_liquido_pregao = -abs(v_liquido_pregao)
            v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
            print(f"    [!] Correção aplicada. Novo Líquido: {v_liquido_pregao} | Novos Custos: {v_custos_unificados}")
            
        print(f"    Bruto Extraído: {v_bruto}")
        print(f"    Custos Calculados: Bruto ({v_bruto}) - Líquido ({v_liquido_pregao}) = {v_custos_unificados}")
        print(f"    Líquido Extraído Direto: {v_liquido_pregao}")
        
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
            'irrf_1': 0.0, # Zerado no banco, pois os custos unificados já engolem B3 + IR1%
            'liquido_pregao': v_liquido_pregao,
            'irrf_19': v_irrf_19,
            'liquido_dia': v_liquido_dia,
            'repasse_dw': v_repasse
        }
    except Exception as e:
        print(f"[BTG_PARSER] Erro crítico: {str(e)}")
        return None