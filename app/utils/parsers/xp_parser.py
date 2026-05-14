import os
import re
import json
import io
import pikepdf
import google.generativeai as genai
from pypdf import PdfReader

def sanitizar_texto(texto, cpf_cliente):
    """Guilhotina de Privacidade (Data Masking) - Remove dados sensíveis antes de enviar à API"""
    texto_limpo = texto
    if cpf_cliente:
        cpf_limpo = ''.join(filter(str.isdigit, str(cpf_cliente)))
        if len(cpf_limpo) == 11:
            cpf_formatado = f"{cpf_limpo[:3]}.{cpf_limpo[3:6]}.{cpf_limpo[6:9]}-{cpf_limpo[9:]}"
            texto_limpo = texto_limpo.replace(cpf_formatado, "[CPF CENSURADO]")
            texto_limpo = texto_limpo.replace(cpf_limpo, "[CPF CENSURADO]")
    
    texto_limpo = re.sub(r'\d{3}\.\d{3}\.\d{3}-\d{2}', '[CPF CENSURADO]', texto_limpo)
    texto_limpo = re.sub(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', '[CNPJ CENSURADO]', texto_limpo)
    
    return texto_limpo

def extrair_dados_xp(caminho_arquivo, cpf_cliente, senha_manual=None):
    print(f"\n" + "="*50)
    print(f"[XP_PARSER] INICIANDO ROBÔ XP V3 (DECRYPT + POWERED BY GEMINI AI)")
    print(f"="*50)
    try:
        # ==================================================
        # DESCRIPTOGRAFIA DO PDF (Mecânica Intacta)
        # ==================================================
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
            texto_original = leitor.pages[-1].extract_text()
                
        except pikepdf.PasswordError:
            raise Exception("SENHA_INCORRETA")
        except Exception:
            try:
                leitor = PdfReader(caminho_arquivo)
                if leitor.is_encrypted:
                    leitor.decrypt(senha_final)
                texto_original = leitor.pages[-1].extract_text()
            except Exception:
                raise Exception("SENHA_INCORRETA")

        if "XP INVESTIMENTOS" not in texto_original.upper():
            return None
        
        print("[XP_PARSER] Senha validada. Sanitizando dados sensíveis (LGPD)...")
        texto_seguro = sanitizar_texto(texto_original, cpf_cliente)

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise Exception("Chave GEMINI_API_KEY não encontrada.")
        
        genai.configure(api_key=api_key)
        
        # ==================================================
        # DIAGNÓSTICO DE API E SELEÇÃO DINÂMICA
        # ==================================================
        print("\n  [GEMINI DIAGNÓSTICO] Verificando ambiente de integração...")
        print(f"    -> Versão do SDK (google-generativeai): {getattr(genai, '__version__', 'Versão não identificada')}")
        
        modelos_suportados = []
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    modelos_suportados.append(m.name)
        except Exception as e:
            print(f"    [!] Falha ao listar modelos do Google: {str(e)}")

        modelos_preferencia = [
            'gemini-2.5-flash',
            'gemini-2.0-flash',
            'gemini-2.0-flash-lite',
            'gemini-1.5-flash'
        ]
        
        modelo_alvo = 'gemini-1.5-flash' # Fallback absoluto
        for pref in modelos_preferencia:
            if f'models/{pref}' in modelos_suportados:
                modelo_alvo = pref
                break
            
        print(f"    -> Modelo validado e acionado para leitura: {modelo_alvo}\n")
        
        model = genai.GenerativeModel(modelo_alvo)
        
        prompt = """
        Você é um analista financeiro extraindo dados de uma nota de corretagem da XP Investimentos.
        
        Encontre exatamente 3 informações financeiras da nota:
        1. Data do Pregão (no formato DD/MM/AAAA).
        2. Valor Bruto do Day Trade (Geralmente atrelado ao termo 'Ajuste day trade').
        3. Total Líquido da Nota (Geralmente atrelado ao termo 'Total líquido da nota').
        
        Regra Estrita de Sinais Financeiros: 
        Se o valor estiver acompanhado da letra 'D' (Débito) na nota, ele DEVE ser negativo no JSON.
        Se o valor estiver acompanhado da letra 'C' (Crédito) na nota, ele DEVE ser positivo no JSON.
        Converta os valores para o formato de programação (ponto como separador decimal, sem separador de milhar).
        
        Retorne ÚNICA e EXCLUSIVAMENTE um objeto JSON válido, sem nenhuma formatação markdown ou texto extra, com esta exata estrutura:
        {
            "data_pregao": "DD/MM/AAAA",
            "bruto": 1230.50,
            "liquido_nota": -450.20
        }
        """
        
        # ==================================================
        # LOG COMPLETO DE INPUT E OUTPUT
        # ==================================================
        print("  [GEMINI REQUEST] Despachando nota mascarada para a nuvem...")
        
        response = model.generate_content([prompt, texto_seguro])
        
        print("  [GEMINI RESPONSE] Resposta bruta devolvida pela IA:")
        print("  --- INÍCIO DO RETORNO ---")
        print(response.text)
        print("  --- FIM DO RETORNO ---\n")
        
        texto_json = response.text.strip()
        if texto_json.startswith("```json"):
            texto_json = texto_json[7:]
        if texto_json.startswith("```"):
            texto_json = texto_json[3:]
        if texto_json.endswith("```"):
            texto_json = texto_json[:-3]
            
        dados_ia = json.loads(texto_json.strip())
        
        data_pregao = dados_ia.get('data_pregao')
        v_bruto = float(dados_ia.get('bruto', 0.0))
        v_liquido_pregao = float(dados_ia.get('liquido_nota', 0.0))

        # ==================================================
        # CÁLCULOS OFF-LINE DA MESA PROPRIETÁRIA
        # ==================================================
        print("\n  [MATEMÁTICA] --- INICIANDO CÁLCULOS OFF-LINE DA MESA ---")
        
        v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
        
        if v_custos_unificados < 0:
            print(f"    [!] Anomalia XP: Custos negativos detectados ({v_custos_unificados}). O PDF inverteu o sinal de loss.")
            v_liquido_pregao = -abs(v_liquido_pregao)
            v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
            print(f"    [!] Correção aplicada. Novo Líquido: {v_liquido_pregao} | Novos Custos: {v_custos_unificados}")
            
        print(f"    Custos Calculados: Bruto ({v_bruto}) - Líquido ({v_liquido_pregao}) = {v_custos_unificados}")
        
        if v_liquido_pregao > 0:
            v_irrf_19 = round(v_liquido_pregao * 0.19, 2)
        else:
            v_irrf_19 = 0.0
            
        v_liquido_dia = round(v_liquido_pregao - v_irrf_19, 2)
        
        if v_liquido_dia > 0:
            v_repasse = round(v_liquido_dia * 0.30, 2)
        else:
            v_repasse = 0.0

        print("  [MATEMÁTICA] --- FIM DOS CÁLCULOS ---\n")

        return {
            'data_pregao': data_pregao,
            'bruto': v_bruto,
            'taxas_b3': v_custos_unificados,
            'irrf_1': 0.0,
            'liquido_pregao': v_liquido_pregao,
            'irrf_19': v_irrf_19,
            'liquido_dia': v_liquido_dia,
            'repasse_dw': v_repasse
        }
    except Exception as e:
        print(f"[XP_PARSER] ERRO: {str(e)}")
        if "SENHA_INCORRETA" in str(e): raise Exception("SENHA_INCORRETA")
        return None