import re
import io
import pikepdf
from pypdf import PdfReader

def extrair_dados_xp(caminho_arquivo, cpf_cliente, senha_manual=None):
    print(f"\n==================================================")
    print(f"[XP_PARSER] INICIANDO ROBÔ SNIPER XP")
    print(f"==================================================")
    print(f"[XP_PARSER] Arquivo alvo: {caminho_arquivo}")
    try:
        if senha_manual:
            senha_final = str(senha_manual).strip()
            print(f"[XP_PARSER] Senha manual recebida: {senha_final}")
        else:
            cpf_limpo = ''.join(filter(str.isdigit, str(cpf_cliente)))
            senha_final = cpf_limpo[-3:] if len(cpf_limpo) >= 3 else ""
            print(f"[XP_PARSER] Tentando senha automática: {senha_final}")
        
        try:
            print("[XP_PARSER] Tentando abrir com o motor PIKEPDF...")
            with pikepdf.open(caminho_arquivo, password=senha_final) as pdf_trancado:
                print("[XP_PARSER] Cadeado aberto! Salvando versão limpa na memória...")
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
            print(f"[XP_PARSER] AVISO: Falha no PIKEPDF. Tentando fallback... ({str(e)})")
            try:
                leitor = PdfReader(caminho_arquivo)
                if leitor.is_encrypted:
                    leitor.decrypt(senha_final)
                ultima_pagina = leitor.pages[-1]
                texto_completo = ultima_pagina.extract_text()
            except Exception:
                raise Exception("SENHA_INCORRETA")

        if "XP INVESTIMENTOS" not in texto_completo.upper():
            return None
        
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo)
        data_pregao = match_data.group(1) if match_data else None

        # PREPARAÇÃO DO RESUMO (Limpeza do Caos e dos Pipes)
        resumo = texto_completo[-2000:]
        resumo_limpo = re.sub(r'[\n\r\|]', ' ', resumo)
        resumo_limpo = re.sub(r'1\s+D\b', ' D', resumo_limpo, flags=re.IGNORECASE)
        resumo_limpo = re.sub(r'1\s+C\b', ' C', resumo_limpo, flags=re.IGNORECASE)

        # 1. Busca todos os valores com C/D (Crédito ou Débito)
        matches_cd = re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*([CDcd])\b", resumo_limpo)
        validos_cd = [(val, letra) for val, letra in matches_cd if val != '0,00']
        
        v_bruto = 0.0
        v_total_liquido = 0.0
        
        if validos_cd:
            # O primeiro valor com C/D é sempre o Bruto (Ajuste Day Trade)
            val_b, let_b = validos_cd[0]
            v_bruto = float(val_b.replace('.', '').replace(',', '.'))
            if let_b.upper() == 'D': v_bruto = -v_bruto
            
            # O último valor com C/D é sempre o Total Líquido da Nota
            val_l, let_l = validos_cd[-1]
            v_total_liquido = float(val_l.replace('.', '').replace(',', '.'))
            if let_l.upper() == 'D': v_total_liquido = -v_total_liquido

        # 2. Busca do IRRF (XP coloca na 2ª posição após o termo)
        v_irrf_1 = 0.0
        match_irrf = re.search(r"IRRF Day Trade", resumo_limpo, re.IGNORECASE)
        if match_irrf:
            bloco = resumo_limpo[match_irrf.end():match_irrf.end()+150]
            nums = re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2})", bloco)
            if len(nums) >= 2:
                v_irrf_1 = float(nums[1].replace('.', '').replace(',', '.'))

        # 3. DEDUÇÃO MATEMÁTICA DAS TAXAS B3
        v_taxas_b3 = round(abs(v_bruto - v_total_liquido) - v_irrf_1, 2)
        v_taxas_b3 = max(0.0, v_taxas_b3) # Prevenção contra números negativos

        print(f"\n  [SNIPER] MATEMÁTICA DEDUTIVA B3:")
        print(f"    -> Bruto Encontrado: {v_bruto}")
        print(f"    -> Total Líquido Encontrado: {v_total_liquido}")
        print(f"    -> IRRF 1% Encontrado: {v_irrf_1}")
        print(f"    -> Taxas B3 Deduzidas: |({v_bruto}) - ({v_total_liquido})| - {v_irrf_1} = {v_taxas_b3}")

        # REPASSE ZERO NO LOSS
        v_liquido_pregao = v_bruto - v_taxas_b3 - v_irrf_1
        v_irrf_19 = v_liquido_pregao * 0.19 if v_liquido_pregao > 0 else 0.0
        v_liquido_dia = v_liquido_pregao - v_irrf_19
        v_repasse = v_liquido_dia * 0.30 if v_liquido_dia > 0 else 0.0

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
        if "SENHA_INCORRETA" in str(e): raise Exception("SENHA_INCORRETA")
        raise Exception(f"Erro na extração XP: {str(e)}")

