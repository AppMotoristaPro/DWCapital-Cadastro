import re
import io
import pikepdf
from pypdf import PdfReader

def extrair_dados_xp(caminho_arquivo, cpf_cliente, senha_manual=None):
    try:
        # 1. Definição da Senha (Prioriza manual, senão usa final do CPF ...819)
        if senha_manual:
            senha_final = str(senha_manual).strip()
        else:
            cpf_limpo = ''.join(filter(str.isdigit, str(cpf_cliente)))
            senha_final = cpf_limpo[-3:] if len(cpf_limpo) >= 3 else ""
        
        # 2. Desbloqueio com pikepdf (Motor de alta compatibilidade)
        try:
            # pikepdf abre o arquivo e remove a criptografia
            with pikepdf.open(caminho_arquivo, password=senha_final) as pdf_trancado:
                # Criamos um buffer na memória para não precisar salvar outro arquivo no disco
                buffer_limpo = io.BytesIO()
                pdf_trancado.save(buffer_limpo)
                buffer_limpo.seek(0)
                
                # Agora o PdfReader lê o arquivo já desbloqueado
                leitor = PdfReader(buffer_limpo)
                ultima_pagina = leitor.pages[-1]
                texto_completo = ultima_pagina.extract_text()
        except pikepdf.PasswordError:
            raise Exception("SENHA_INCORRETA")
        except Exception as e:
            # Fallback para caso o PDF já esteja sem senha
            try:
                leitor = PdfReader(caminho_arquivo)
                ultima_pagina = leitor.pages[-1]
                texto_completo = ultima_pagina.extract_text()
            except:
                raise Exception("SENHA_INCORRETA")

        # BLOQUEIO DE SEGURANÇA: Verifica se o PDF é realmente da XP
        if "XP INVESTIMENTOS" not in texto_completo.upper():
            return None
        
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo)
        data_pregao = match_data.group(1) if match_data else None

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

        # Regras XP (Mantidas conforme sua lógica original de extração)
        v_bruto = extrair_por_posicao(r"Valor dos negócios", texto_completo, 1)
        v_irrf_1 = extrair_por_posicao(r"IRRF Day Trade", texto_completo, 1) 
        v_taxas_b3 = extrair_por_posicao(r"Total de custos operacionais", texto_completo, 1)

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
        if "SENHA_INCORRETA" in str(e):
            raise Exception("SENHA_INCORRETA")
        raise Exception(f"Erro na extração XP: {str(e)}")

