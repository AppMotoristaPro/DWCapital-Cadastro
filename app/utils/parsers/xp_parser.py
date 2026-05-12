import re
import io
import pikepdf
from pypdf import PdfReader

def extrair_dados_xp(caminho_arquivo, cpf_cliente, senha_manual=None):
    print(f"\n==================================================")
    print(f"[XP_PARSER] INICIANDO ROBÔ XP (ESTRATÉGIA UNIFICADA)")
    print(f"==================================================")
    try:
        if senha_manual:
            senha_final = str(senha_manual).strip()
        else:
            cpf_limpo = ''.join(filter(str.isdigit, str(cpf_cliente)))
            senha_final = cpf_limpo[-3:] if len(cpf_limpo) >= 3 else ""
        
        try:
            with pikepdf.open(caminho_arquivo, password=senha_final) as pdf_trancado:
                buffer_limpo = io.BytesIO()
                pdf_trancado.save(buffer_limpo)
                buffer_limpo.seek(0)
            
            with open(caminho_arquivo, "wb") as f_out:
                f_out.write(buffer_limpo.getvalue())

            leitor = PdfReader(buffer_limpo)
            ultima_pagina = leitor.pages[-1]
            texto_completo_original = ultima_pagina.extract_text()
                
        except pikepdf.PasswordError:
            raise Exception("SENHA_INCORRETA")
        except Exception:
            try:
                leitor = PdfReader(caminho_arquivo)
                if leitor.is_encrypted:
                    leitor.decrypt(senha_final)
                ultima_pagina = leitor.pages[-1]
                texto_completo_original = ultima_pagina.extract_text()
            except Exception:
                raise Exception("SENHA_INCORRETA")

        if "XP INVESTIMENTOS" not in texto_completo_original.upper():
            return None
        
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo_original)
        data_pregao = match_data.group(1) if match_data else None

        # --- A VACINA CONTRA O LIXO DO RODAPÉ ---
        texto_completo = re.split(r'Custos BM&F', texto_completo_original, flags=re.IGNORECASE)[0]

        def extrair_por_posicao(nome_campo, padrao, texto, posicao, aceita_cd=False, janela_tras=0, janela_frente=250):
            print(f"\n  [BUSCA] Campo: '{nome_campo}'")
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                inicio = max(0, match.start() - janela_tras)
                fim = min(len(texto), match.end() + janela_frente)
                bloco = texto[inicio:fim]

                bloco_limpo = re.sub(r'[\|/]', ' ', bloco)
                bloco_limpo = re.sub(r'(,\d{2})\s*([CDcd])\b', r'\1 \2', bloco_limpo)

                regex_numeros = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s*([CDcd])?"
                matches = re.findall(regex_numeros, bloco_limpo)

                print(f"    -> Valores localizados na janela:")
                for i, m in enumerate(matches):
                    l_print = m[1] if m[1] else "(Sem Letra)"
                    print(f"       [Pos: {i+1}] -> {m[0]} {l_print}")

                if matches:
                    try:
                        if posicao > 0:
                            alvo = matches[posicao - 1]
                        else:
                            alvo = matches[posicao] 
                            
                        valor_str, letra = alvo
                        num = float(valor_str.replace('.', '').replace(',', '.'))

                        if aceita_cd:
                            if letra and letra.upper() == 'D':
                                num = -num
                                print(f"    -> [!] Débito detectado: {num}")
                            else:
                                print(f"    -> [!] Crédito detectado: {num}")
                        else:
                            num = abs(num)
                        return num
                    except IndexError:
                        print(f"    -> [ERRO] Posição {posicao} não encontrada.")
            return 0.0

        # --- NOVA EXTRAÇÃO SIMPLIFICADA (BRUTO E LÍQUIDO) ---
        v_bruto = extrair_por_posicao("Valor Bruto", r"Ajuste day trade", texto_completo, 4, aceita_cd=True)
        
        # Na XP, pegamos o último valor atrelado à âncora do Total Líquido expandindo a janela para 1500
        v_liquido_pregao = extrair_por_posicao("Líquido da Nota", r"Total l[ií]quido da nota", texto_completo, -1, aceita_cd=True, janela_frente=1500)

        print("\n  [MATEMÁTICA] --- PROCESSAMENTO ---")
        
        v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
        print(f"    Custos Calculados: Bruto ({v_bruto}) - Líquido ({v_liquido_pregao}) = {v_custos_unificados}")

        v_taxas_b3 = v_custos_unificados
        v_irrf_1 = 0.0

        print(f"    Líquido Pregão (Extraído Direto): {v_liquido_pregao}")
        
        v_irrf_19 = round(v_liquido_pregao * 0.19, 2) if v_liquido_pregao > 0 else 0.0
        v_liquido_dia = round(v_liquido_pregao - v_irrf_19, 2)
        
        v_repasse = round(v_liquido_dia * 0.30, 2) if v_liquido_dia > 0 else 0.0
        print(f"    Repasse DW Final: R$ {v_repasse}")

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
        print(f"[XP_PARSER] ERRO: {str(e)}")
        if "SENHA_INCORRETA" in str(e): raise Exception("SENHA_INCORRETA")
        return None

