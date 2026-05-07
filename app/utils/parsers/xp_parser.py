import re
import io
import pikepdf
from pypdf import PdfReader

def extrair_dados_xp(caminho_arquivo, cpf_cliente, senha_manual=None):
    print(f"[XP_PARSER] Iniciando robô XP. Arquivo: {caminho_arquivo}")
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
            
            # MAGIA ACONTECENDO AQUI: Substituímos o arquivo trancado pelo arquivo limpo no disco.
            # Assim, quando a rota mandar o arquivo pro Cloudinary, ele já vai sem senha!
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
        print(f"[XP_PARSER] Data encontrada: {data_pregao}")

        def limpar_valor(resultado):
            if not resultado: return 0.0
            resultado = re.sub(r'[^\d,.]', '', resultado)
            if ',' in resultado:
                val = resultado.replace('.', '').replace(',', '.')
            else:
                val = resultado
            try:
                return float(val)
            except:
                return 0.0

        def extrair_por_posicao(padrao, texto, posicao):
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                bloco_depois = texto[match.end():match.end()+200]
                numeros = re.findall(r"(\d[\d\.,]*[\.,]\d{2})", bloco_depois)
                if numeros and len(numeros) >= posicao:
                    return limpar_valor(numeros[posicao - 1])
            return 0.0

        print("[XP_PARSER] Extraindo valores financeiros...")
        v_bruto = extrair_por_posicao(r"Valor dos negócios", texto_completo, 5)
        v_irrf_1 = extrair_por_posicao(r"IRRF Day Trade", texto_completo, 2) 
        v_taxas_b3 = extrair_por_posicao(r"Total de custos operacionais", texto_completo, 5)

        v_liquido_pregao = v_bruto - v_taxas_b3 - v_irrf_1
        v_irrf_19 = v_liquido_pregao * 0.19 if v_liquido_pregao > 0 else 0.0
        v_liquido_dia = v_liquido_pregao - v_irrf_19
        v_repasse = v_liquido_dia * 0.30 if v_liquido_dia > 0 else 0.0
        
        print(f"[XP_PARSER] Valores capturados: Bruto={v_bruto}, Taxas={v_taxas_b3}, Repasse={v_repasse}")

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

