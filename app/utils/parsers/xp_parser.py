import re
from pypdf import PdfReader

def extrair_dados_xp(caminho_arquivo, cpf_cliente):
    try:
        # 1. Preparação da Senha (Garante que pegamos os 3 dígitos finais do CPF 819)
        cpf_limpo = ''.join(filter(str.isdigit, str(cpf_cliente)))
        senha_final = cpf_limpo[-3:] if len(cpf_limpo) >= 3 else ""
        
        # 2. Abertura Direta com Senha (Evita o erro de 'Not Supported')
        # Tentamos abrir já passando a senha na inicialização
        try:
            leitor = PdfReader(caminho_arquivo, password=senha_final)
        except:
            # Fallback caso a versão da biblioteca peça abertura simples primeiro
            leitor = PdfReader(caminho_arquivo)
            if leitor.is_encrypted:
                leitor.decrypt(senha_final)

        # 3. Validação de Acesso
        try:
            ultima_pagina = leitor.pages[-1]
            texto_completo = ultima_pagina.extract_text()
        except Exception as e:
            raise Exception(f"Cadeado não abriu. A senha '{senha_final}' foi rejeitada pelo PDF da XP.")
        
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

        # Regras XP atualizadas
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
        raise Exception(str(e))

