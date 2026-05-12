import re
from pypdf import PdfReader

def extrair_dados_genial(caminho_arquivo):
    print(f"\n==================================================")
    print(f"[GENIAL_PARSER] INICIANDO ROBÔ GENIAL (UNIFICADA + BLINDADA)")
    print(f"==================================================")
    print(f"[GENIAL_PARSER] Arquivo alvo: {caminho_arquivo}")
    try:
        leitor = PdfReader(caminho_arquivo)
        ultima_pagina = leitor.pages[-1]
        texto_completo_original = ultima_pagina.extract_text()
        print("[GENIAL_PARSER] Texto lido com sucesso.")

        if "GENIAL" not in texto_completo_original.upper():
            print("[GENIAL_PARSER] ERRO: O PDF não pertence à Genial Investimentos.")
            return None

        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo_original)
        data_pregao = match_data.group(1) if match_data else None
        print(f"[GENIAL_PARSER] Data encontrada: {data_pregao}\n")

        # --- A VACINA CONTRA O LIXO DO RODAPÉ ---
        # Cortamos todo o texto de rodapé (taxas fixas e regras de ouro) para que o "-1" seja realmente o final
        texto_completo = re.split(r'Custos BM&F', texto_completo_original, flags=re.IGNORECASE)[0]

        def extrair_por_posicao(nome_campo, padrao, texto, posicao, aceita_cd=False, janela_tras=0, janela_frente=200):
            print(f"\n  [BUSCA] Analisando Campo: '{nome_campo}'")
            print(f"  [BUSCA] Padrão (Regex): '{padrao}' | Posição-Alvo: {posicao} | Janela: -{janela_tras} a +{janela_frente}")

            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                inicio = max(0, match.start() - janela_tras)
                fim = min(len(texto), match.end() + janela_frente)
                bloco = texto[inicio:fim]

                bloco_limpo = bloco.replace('|', ' ')
                bloco_limpo = re.sub(r'(,\d{2})\s+(?:0,00\s*)+([CDcd])\b', r'\1 \2', bloco_limpo, flags=re.IGNORECASE)
                bloco_limpo = re.sub(r'(,\d{2})\s*([CDcd])\b', r'\1 \2', bloco_limpo, flags=re.IGNORECASE)

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
                                print(f"    -> [SUCESSO] Nenhuma letra detectada. Retornando Positivo: {num}")
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

        # --- NOVA EXTRAÇÃO SIMPLIFICADA (BRUTO E LÍQUIDO) ---
        v_bruto = extrair_por_posicao("Valor Bruto", r"Valor dos negócios", texto_completo, 1, aceita_cd=True, janela_tras=0, janela_frente=200)
        
        # Como limpamos o rodapé, a posição -1 achará com perfeição o valor absoluto correto
        v_liquido_pregao = extrair_por_posicao("Líquido da Nota", r"Total l[ií]quido da nota", texto_completo, -1, aceita_cd=True, janela_tras=0, janela_frente=200)

        print("\n  [MATEMÁTICA] --- INICIANDO CÁLCULOS DO PREGÃO ---")
        
        # Custos Operacionais = Diferença Absoluta entre o Bruto e o Líquido
        v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
        print(f"    Custos Calculados: Bruto ({v_bruto}) - Líquido ({v_liquido_pregao}) = {v_custos_unificados}")

        # Para manter compatibilidade com o Banco de Dados
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
        print(f"[GENIAL_PARSER] Erro crítico: {str(e)}")
        return None

