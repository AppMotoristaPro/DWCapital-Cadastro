import re
import io
import pikepdf
from pypdf import PdfReader

def extrair_dados_xp(caminho_arquivo, cpf_cliente, senha_manual=None):
    print(f"\n==================================================")
    print(f"[XP_PARSER] INICIANDO ROBÔ XP (ALVO: AJUSTE DAY TRADE)")
    print(f"==================================================")
    print(f"[XP_PARSER] Arquivo alvo: {caminho_arquivo}")
    try:
        # 1. Tratamento de Senha (Padrão XP)
        if senha_manual:
            senha_final = str(senha_manual).strip()
            print(f"[XP_PARSER] Senha manual recebida: {senha_final}")
        else:
            cpf_limpo = ''.join(filter(str.isdigit, str(cpf_cliente)))
            senha_final = cpf_limpo[-3:] if len(cpf_limpo) >= 3 else ""
            print(f"[XP_PARSER] Tentando senha automática: {senha_final}")
        
        # 2. [span_2](start_span)[span_3](start_span)Desbloqueio e Leitura[span_2](end_span)[span_3](end_span)
        try:
            with pikepdf.open(caminho_arquivo, password=senha_final) as pdf_trancado:
                buffer_limpo = io.BytesIO()
                pdf_trancado.save(buffer_limpo)
                buffer_limpo.seek(0)
            
            with open(caminho_arquivo, "wb") as f_out:
                f_out.write(buffer_limpo.getvalue())

            leitor = PdfReader(buffer_limpo)
            ultima_pagina = leitor.pages[-1]
            texto_completo = ultima_pagina.extract_text()
            print("[XP_PARSER] Texto extraído com sucesso.")
                
        except pikepdf.PasswordError:
            print("[XP_PARSER] ERRO: Senha incorreta.")
            raise Exception("SENHA_INCORRETA")
        except Exception as e:
            print(f"[XP_PARSER] Fallback necessário... ({str(e)})")
            try:
                leitor = PdfReader(caminho_arquivo)
                if leitor.is_encrypted:
                    leitor.decrypt(senha_final)
                ultima_pagina = leitor.pages[-1]
                texto_completo = ultima_pagina.extract_text()
            except Exception:
                raise Exception("SENHA_INCORRETA")

        if "XP INVESTIMENTOS" not in texto_completo.upper():
            print("[XP_PARSER] ERRO: Assinatura da XP não encontrada.")
            return None
        
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo)
        data_pregao = match_data.group(1) if match_data else None
        print(f"[XP_PARSER] Data encontrada: {data_pregao}")

        def extrair_por_posicao(nome_campo, padrao, texto, posicao, aceita_cd=False, janela_tras=0, janela_frente=200):
            print(f"\n  [BUSCA] Campo: '{nome_campo}'")
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                inicio = max(0, match.start() - janela_tras)
                fim = min(len(texto), match.end() + janela_frente)
                bloco = texto[inicio:fim]

                # LIMPEZA ESPECÍFICA XP: Remove barras verticais | e inclinadas /
                bloco_limpo = re.sub(r'[\|/]', ' ', bloco)
                
                # Arruma letras grudadas (Ex: 75,00C -> 75,00 C)
                bloco_limpo = re.sub(r'(,\d{2})\s*([CDcd])\b', r'\1 \2', bloco_limpo)

                # [span_4](start_span)REGEX PARA NÚMEROS E LETRAS[span_4](end_span)
                regex_numeros = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s*([CDcd])?"
                matches = re.findall(regex_numeros, bloco_limpo)

                print(f"    -> Valores localizados na janela:")
                for i, m in enumerate(matches):
                    idx_rev = i - len(matches)
                    l_print = m[1] if m[1] else "(Sem Letra)"
                    print(f"       [Pos: {i+1} | Rev: {idx_rev}] -> {m[0]} {l_print}")

                if matches:
                    try:
                        alvo = matches[posicao - 1] if posicao > 0 else matches[posicao]
                        valor_str, letra = alvo
                        num = float(valor_str.replace('.', '').replace(',', '.'))

                        if aceita_cd:
                            if letra and letra.upper() == 'D':
                                num = -num
                                print(f"    -> [!] Letra 'D' aplicada: {num}")
                            elif letra and letra.upper() == 'C':
                                print(f"    -> [!] Letra 'C' aplicada: {num}")
                        else:
                            num = abs(num)
                            print(f"    -> [!] Campo de Despesa forçado absoluto: {num}")
                        return num
                    except IndexError:
                        print(f"    -> [ERRO] Posição {posicao} inexistente.")
            return 0.0

        # --- NOVA CONFIGURAÇÃO DE ALVOS XP ---
        
        # 1. Bruto: Alterado para 'Ajuste day trade' na Posição 1 para pegar o lucro real (75,00 C)
        v_bruto = extrair_por_posicao("Valor Bruto", r"Ajuste day trade", texto_completo, 1, aceita_cd=True)
        
        # 2. IRRF 1%: Mantido na posição 2 após a palavra-chave
        v_irrf_1 = extrair_por_posicao("IRRF Day Trade (1%)", r"IRRF Day Trade", texto_completo, 2, aceita_cd=False)
        
        # 3. Taxas B3: Mantido na posição 5 de custos operacionais consolidado (38,89 D)
        v_taxas_b3 = extrair_por_posicao("Taxas B3", r"Total de custos operacionais", texto_completo, 5, aceita_cd=False)

        print("\n  [MATEMÁTICA] --- PROCESSAMENTO FINAL ---")
        # Líquido do Pregão considera o Ajuste Day Trade menos taxas e IRRF
        v_liquido_pregao = round(v_bruto - v_taxas_b3 - v_irrf_1, 2)
        print(f"    Líquido Pregão (Day Trade): {v_liquido_pregao}")
        
        v_irrf_19 = round(v_liquido_pregao * 0.19, 2) if v_liquido_pregao > 0 else 0.0
        v_liquido_dia = round(v_liquido_pregao - v_irrf_19, 2)
        
        # [span_5](start_span)REPASSE DE 30% SOBRE O RESULTADO DO DAY TRADE[span_5](end_span)
        v_repasse = round(v_liquido_dia * 0.30, 2) if v_liquido_dia > 0 else 0.0
        print(f"    Repasse DW Calculado: R$ {v_repasse}")

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
        print(f"[XP_PARSER] ERRO CRÍTICO: {str(e)}")
        if "SENHA_INCORRETA" in str(e): raise Exception("SENHA_INCORRETA")
        return None

