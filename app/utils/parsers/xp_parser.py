import re
import io
import pikepdf
from pypdf import PdfReader

def extrair_dados_xp(caminho_arquivo, cpf_cliente, senha_manual=None):
    print(f"\n==================================================")
    print(f"[XP_PARSER] INICIANDO ROBÔ XP")
    print(f"==================================================")
    print(f"[XP_PARSER] Arquivo alvo: {caminho_arquivo}")
    try:
        # 1. Definição da Senha
        if senha_manual:
            senha_final = str(senha_manual).strip()
            print(f"[XP_PARSER] Senha manual recebida: {senha_final}")
        else:
            cpf_limpo = ''.join(filter(str.isdigit, str(cpf_cliente)))
            senha_final = cpf_limpo[-3:] if len(cpf_limpo) >= 3 else ""
            print(f"[XP_PARSER] Tentando senha automática (final CPF): {senha_final}")
        
        # 2. Desbloqueio com pikepdf e Sobrescrita do Arquivo
        try:
            print("[XP_PARSER] Tentando abrir com o motor PIKEPDF...")
            with pikepdf.open(caminho_arquivo, password=senha_final) as pdf_trancado:
                print("[XP_PARSER] Cadeado aberto! Salvando versão limpa na memória...")
                buffer_limpo = io.BytesIO()
                pdf_trancado.save(buffer_limpo)
                buffer_limpo.seek(0)
            
            with open(caminho_arquivo, "wb") as f_out:
                f_out.write(buffer_limpo.getvalue())
            print("[XP_PARSER] Arquivo original sobrescrito com sucesso (Cadeado removido).")

            print("[XP_PARSER] Extraindo texto da memória...")
            leitor = PdfReader(buffer_limpo)
            ultima_pagina = leitor.pages[-1]
            texto_completo = ultima_pagina.extract_text()
            print("[XP_PARSER] Texto extraído com sucesso pelo PIKEPDF.")
                
        except pikepdf.PasswordError:
            print("[XP_PARSER] ERRO: PIKEPDF rejeitou a senha.")
            raise Exception("SENHA_INCORRETA")
        except Exception as e:
            print(f"[XP_PARSER] AVISO: Falha no PIKEPDF ({str(e)}). Tentando motor secundário (PdfReader)...")
            try:
                leitor = PdfReader(caminho_arquivo)
                if leitor.is_encrypted:
                    leitor.decrypt(senha_final)
                ultima_pagina = leitor.pages[-1]
                texto_completo = ultima_pagina.extract_text()
                print("[XP_PARSER] Texto extraído com sucesso pelo fallback (PdfReader).")
            except Exception as e2:
                print(f"[XP_PARSER] ERRO: Fallback falhou também. Senha incorreta ou arquivo corrompido.")
                raise Exception("SENHA_INCORRETA")

        print("[XP_PARSER] Validando assinatura da corretora...")
        if "XP INVESTIMENTOS" not in texto_completo.upper():
            print("[XP_PARSER] ERRO: Assinatura da XP não encontrada no documento.")
            return None
        
        print("[XP_PARSER] Buscando data do pregão...")
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo)
        data_pregao = match_data.group(1) if match_data else None
        print(f"[XP_PARSER] Data encontrada: {data_pregao}\n")

        def extrair_por_posicao(nome_campo, padrao, texto, posicao, aceita_cd=False):
            print(f"  [BUSCA] Campo: '{nome_campo}' | Padrão: '{padrao}' | Posição: {posicao}")
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                bloco_depois = texto[match.end():match.end()+200]
                print(f"    -> Bloco extraído: {repr(bloco_depois[:60])}...")
                
                # Regex captura o número e a letra D/C (se existir) ignorando espaços
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
                        num = abs(num) # Garante que as taxas não buguem a matemática
                        print(f"    -> [!] Campo de Despesa. Forçado para absoluto POSITIVO: {num}")
                        
                    return num
                else:
                    print(f"    -> [ERRO] Posição {posicao} não existe. Encontrados apenas {len(matches)} itens.")
            else:
                print(f"    -> [ERRO] Padrão não encontrado no PDF.")
            return 0.0

        # --- EXTRAÇÃO DE DADOS ---
        v_bruto = extrair_por_posicao("Valor Bruto", r"Valor dos negócios", texto_completo, 5, aceita_cd=True)
        v_irrf_1 = extrair_por_posicao("IRRF Day Trade (1%)", r"IRRF Day Trade", texto_completo, 2, aceita_cd=False) 
        v_taxas_b3 = extrair_por_posicao("Taxas B3", r"Total de custos operacionais", texto_completo, 5, aceita_cd=False)

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
        print(f"[XP_PARSER] EXCEÇÃO CRÍTICA: {str(e)}")
        if "SENHA_INCORRETA" in str(e):
            raise Exception("SENHA_INCORRETA")
        raise Exception(f"Erro na extração XP: {str(e)}")

