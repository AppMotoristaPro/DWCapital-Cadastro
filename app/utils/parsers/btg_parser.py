import re
from pypdf import PdfReader

def extrair_dados_btg(caminho_arquivo):
    print(f"\n==================================================")
    print(f"[BTG_PARSER] INICIANDO ROBÔ BTG (ESTRATÉGIA UNIFICADA)")
    print(f"==================================================")
    print(f"[BTG_PARSER] Arquivo alvo: {caminho_arquivo}")
    try:
        leitor = PdfReader(caminho_arquivo)
        ultima_pagina = leitor.pages[-1]
        texto_completo_original = ultima_pagina.extract_text()
        print("[BTG_PARSER] Texto lido com sucesso.")
        
        if "BTG PACTUAL" not in texto_completo_original.upper():
            print("[BTG_PARSER] ERRO: O PDF não pertence ao BTG Pactual.")
            return None
        
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo_original)
        data_pregao = match_data.group(1) if match_data else None
        print(f"[BTG_PARSER] Data encontrada: {data_pregao}\n")

        # --- LIMPEZA CIRÚRGICA DE RODAPÉ ---
        # Substitui os valores fantasmas por espaço para não explodir a linha e preservar as âncoras
        texto_completo = texto_completo_original
        texto_completo = re.sub(r'(?:OZ1|OZ2|OZ3)[-\s]*\d+,\d+\s*grs\.?', ' ', texto_completo, flags=re.IGNORECASE)
        texto_completo = re.sub(r'(?:0800|4007|4004)[-\s]*\d{3,4}[-\s]*\d{4}', ' ', texto_completo)
        texto_completo = re.sub(r'Total remunera[çc][ãa]o.*', ' ', texto_completo, flags=re.IGNORECASE)

        def extrair_por_posicao(nome_campo, padrao, texto, posicao, aceita_cd=False, janela_tras=0, janela_frente=200):
            print(f"\n  [BUSCA] Analisando Campo: '{nome_campo}'")
            print(f"  [BUSCA] Padrão (Regex): '{padrao}' | Posição-Alvo: {posicao} | Janela: -{janela_tras} a +{janela_frente}")
            
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
                
                print(f"    -> Valores e Letras localizados na janela:")
                for i, m in enumerate(matches):
                    idx_rev = i - len(matches)
                    letra_print = m[1] if m[1] else "(Sem Letra)"
                    print(f"       [Pos: {i+1} | Rev: {idx_rev}] -> {m[0]} {letra_print}")
                
                if matches:
                    try:
                        if posicao > 0:
                            alvo = matches[posicao - 1]
                        else:
                            alvo = matches[posicao] 
                            
                        valor_str, letra = alvo
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

        # --- ESTRATÉGIA UNIFICADA (BRUTO E LÍQUIDO) ---
        v_bruto = extrair_por_posicao("Valor Bruto", r"Ajuste day trade", texto_completo, 10, aceita_cd=True, janela_tras=0, janela_frente=300)
        
        # Janela ampla para frente e para trás para garantir a captura independentemente da ordem do parser
        v_liquido_pregao = extrair_por_posicao("Líquido da Nota", r"Total l[ií]quido da nota", texto_completo, -1, aceita_cd=True, janela_tras=500, janela_frente=1500)

        print("\n  [MATEMÁTICA] --- INICIANDO CÁLCULOS DO PREGÃO ---")
        
        v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
        
        # --- A VACINA MATEMÁTICA: CORREÇÃO DE SINAL ---
        if v_custos_unificados < 0:
            print(f"    [!] Anomalia detectada: Custos negativos ({v_custos_unificados}). O PDF ocultou o sinal de Loss!")
            v_liquido_pregao = -abs(v_liquido_pregao)
            v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
            print(f"    [!] Correção aplicada. Novo Líquido: {v_liquido_pregao} | Novos Custos: {v_custos_unificados}")
        else:
            print(f"    Custos Calculados: Bruto ({v_bruto}) - Líquido ({v_liquido_pregao}) = {v_custos_unificados}")

        # Para manter compatibilidade com o Banco de Dados sem migrations
        v_taxas_b3 = v_custos_unificados
        v_irrf_1 = 0.0

        print(f"    Fórmula: Líquido Pregão (Extraído Direto) = {v_liquido_pregao}")
        
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

