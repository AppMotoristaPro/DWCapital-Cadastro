import re
from pypdf import PdfReader

def extrair_dados_btg(caminho_arquivo):
    print(f"\n==================================================")
    print(f"[BTG_PARSER] INICIANDO ROBÔ BTG (POSIÇÃO + LETRA + JANELA)")
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
            print(f"  [BUSCA] Padrão (Regex): '{padrao}' | Posição-Alvo: {posicao} | Janela: -{janela_tras} a +{janela_frente}")
            
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                # O Pulo do Gato: Captura o texto ANTES e DEPOIS da palavra-chave
                inicio = max(0, match.start() - janela_tras)
                fim = min(len(texto), match.end() + janela_frente)
                bloco = texto[inicio:fim]
                
                print(f"    -> [TEXTO CRU LIDO]:")
                print(f"       {repr(bloco)}")
                
                # 1. Limpeza do Caos B3/PDF
                bloco_limpo = bloco.replace('|', ' ')
                # Se o leitor do PDF transformou a barra '|' em '1' antes das letras:
                bloco_limpo = re.sub(r'\b1\s+D\b', ' D', bloco_limpo, flags=re.IGNORECASE)
                bloco_limpo = re.sub(r'\b1\s+C\b', ' C', bloco_limpo, flags=re.IGNORECASE)
                bloco_limpo = re.sub(r'(,\d{2})1\s*([CDcd])\b', r'\1 \2', bloco_limpo) # Limpa 184,101 D -> 184,10 D
                bloco_limpo = re.sub(r'(,\d{2})\s*([CDcd])\b', r'\1 \2', bloco_limpo)
                
                print(f"    -> [TEXTO LIMPO (Tratamento de Letras e Pipes)]:")
                print(f"       {repr(bloco_limpo)}")

                # 2. A REGEX PREDADORA: Procura o número e Opcionalmente o C ou D logo na frente
                regex_numeros = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s*([CDcd])?"
                matches = re.findall(regex_numeros, bloco_limpo)
                
                print(f"    -> Valores e Letras localizados na janela:")
                for i, m in enumerate(matches):
                    # Mostra a posição da esquerda pra direita (Positiva) e da direita pra esquerda (Negativa)
                    idx_rev = i - len(matches)
                    letra_print = m[1] if m[1] else "(Sem Letra)"
                    print(f"       [Pos: {i+1} | Rev: {idx_rev}] -> {m[0]} {letra_print}")
                
                if matches:
                    try:
                        if posicao > 0:
                            alvo = matches[posicao - 1]
                        else:
                            alvo = matches[posicao] # Se for negativo, pega de trás pra frente
                            
                        valor_str, letra = alvo
                        
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
                                print(f"    -> [SUCESSO] Nenhuma letra C/D detectada. Assumindo Positivo: {num}")
                        else:
                            num = abs(num) 
                            print(f"    -> [SUCESSO] Campo de Despesa/Taxa. Forçado Absoluto: {num}")
                            
                        return num
                    except IndexError:
                        print(f"    -> [ERRO] A posição {posicao} não existe na lista acima.")
                else:
                    print(f"    -> [ERRO] Nenhum número encontrado na janela.")
            else:
                print(f"    -> [ERRO] A palavra-chave '{padrao}' sumiu do PDF.")
            return 0.0

        # --- EXTRAÇÃO DE DADOS POR POSIÇÃO NO BTG ---
        
        # 1. Bruto (Ajuste Day Trade)
        # Olhando apenas para a frente. O log anterior mostrou que o valor 1.230,00 caiu na posição 10.
        v_bruto = extrair_por_posicao("Valor Bruto", r"Ajuste day trade", texto_completo, 10, aceita_cd=True, janela_tras=0, janela_frente=300)
        
        # 2. IRRF Day Trade (1%)
        # Como o BTG cola o número nas costas da palavra ("10,45IRRF Day Trade (proj.)"),
        # vamos olhar 40 caracteres para trás e pegar a posição -1 (O último número lido antes da palavra).
        v_irrf_1 = extrair_por_posicao("IRRF Day Trade (1%)", r"IRRF Day Trade \(proj\.\)", texto_completo, -1, aceita_cd=False, janela_tras=40, janela_frente=0)
        
        # 3. Taxas B3
        # Como o BTG também cola nas costas ("184,10Total das despesas"), usamos a mesma lógica de olhar para trás.
        v_taxas_b3 = extrair_por_posicao("Taxas B3", r"Total das despesas", texto_completo, -1, aceita_cd=False, janela_tras=40, janela_frente=0)

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

