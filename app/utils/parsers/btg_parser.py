import os
import re
import json
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

def extrair_dados_btg(caminho_arquivo, cpf_cliente=None):
    print(f"\n" + "="*50)
    print(f"[BTG_PARSER] INICIANDO ROBÔ BTG V3 (POWERED BY GEMINI AI)")
    print(f"="*50)
    try:
        leitor = PdfReader(caminho_arquivo)
        texto_full = leitor.pages[-1].extract_text()
        print("[BTG_PARSER] Texto extraído. Otimizando para a IA...")

        if "BTG PACTUAL" not in texto_full.upper():
            print("[BTG_PARSER] ERRO: O PDF não pertence ao BTG Pactual.")
            return None

        # OTIMIZAÇÃO DE CONTEXTO: Corta o miolo (operações) e junta Cabeçalho com Rodapé
        if len(texto_full) > 2500:
            texto_original = texto_full[:1000] + "\n\n... [OPERAÇÕES OCULTAS PARA POUPAR A IA] ...\n\n" + texto_full[-1500:]
        else:
            texto_original = texto_full

        print("[BTG_PARSER] Sanitizando dados sensíveis (LGPD)...")
        texto_seguro = sanitizar_texto(texto_original, cpf_cliente)

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise Exception("Chave GEMINI_API_KEY não encontrada no ambiente (.env ou Render).")
        
        genai.configure(api_key=api_key)
        
        print("\n  [GEMINI DIAGNÓSTICO] Verificando ambiente de integração...")
        print(f"    -> Versão do SDK (google-generativeai): {getattr(genai, '__version__', 'Versão não identificada')}")
        
        modelos_suportados = []
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    modelos_suportados.append(m.name)
        except Exception as e:
            print(f"    [!] Falha ao listar modelos do Google: {str(e)}")

        # INVERSÃO DE PRIORIDADE: 1.5 no topo para garantir 1500 requisições gratuitas/dia
        modelos_preferencia = [
            'gemini-1.5-flash',
            'gemini-2.0-flash-lite',
            'gemini-2.0-flash',
            'gemini-2.5-flash'
        ]
        
        modelo_alvo = 'gemini-1.5-flash'
        for pref in modelos_preferencia:
            if f'models/{pref}' in modelos_suportados:
                modelo_alvo = pref
                break
            
        print(f"    -> Modelo validado e acionado para leitura: {modelo_alvo}\n")
        
        model = genai.GenerativeModel(modelo_alvo)
        
        prompt = """
        Você é um auditor financeiro especialista na extração de dados de notas de corretagem da BTG Pactual.
        O texto do PDF sofreu quebra de colunas. Palavras, números e as letras 'C' (Crédito) e 'D' (Débito) estão completamente misturados ou fora de ordem.
        Muitas vezes a letra 'D' está colada no número (ex: 820,00D).
        
        Encontre 3 informações exatas no cabeçalho/rodapé:
        1. Data do Pregão (DD/MM/AAAA).
        2. Valor Bruto: Procure por 'Ajuste day trade' ou 'Valor dos negócios'. Pegue o valor não zerado.
        3. Total Líquido: Procure por 'Total líquido da nota'. Na BTG, geralmente é o último valor financeiro no final do documento.
        
        REGRA MATEMÁTICA CRÍTICA:
        Sempre verifique se há um 'D' (Débito) ou 'C' (Crédito) atrelado ao valor (colado ou em rodapé). Se houver 'D', o valor DEVE TER SINAL NEGATIVO (-).
        
        Retorne EXCLUSIVAMENTE um JSON válido. Use o campo 'raciocinio' para explicar a captura antes dos valores finais.
        Estrutura obrigatória de exemplo:
        {
            "raciocinio": "Achei Ajuste day trade 820,00D (Sinal negativo). O líquido é 847,00 com D no final (Sinal negativo).",
            "data_pregao": "06/05/2026",
            "bruto": -820.00,
            "liquido_nota": -847.00
        }
        """
        
        print("  [GEMINI REQUEST] Despachando nota mascarada para a nuvem...")
        print("  --- INÍCIO DO TEXTO ENVIADO (REDUZIDO) ---")
        print(texto_seguro)
        print("  --- FIM DO TEXTO ENVIADO ---\n")
        
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
        
        print("  [MATEMÁTICA] --- INICIANDO CÁLCULOS OFF-LINE DA MESA ---")
        
        v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
        
        if v_custos_unificados < 0:
            print(f"    [!] Anomalia BTG: Custos negativos detectados ({v_custos_unificados}). O PDF inverteu o sinal de loss.")
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
        print(f"[BTG_PARSER] Erro crítico na extração inteligente: {str(e)}")
        return None