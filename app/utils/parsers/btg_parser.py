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
    
    # Censura genérica para outros CPFs e CNPJs que possam estar na nota
    texto_limpo = re.sub(r'\d{3}\.\d{3}\.\d{3}-\d{2}', '[CPF CENSURADO]', texto_limpo)
    texto_limpo = re.sub(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', '[CNPJ CENSURADO]', texto_limpo)
    
    return texto_limpo

def extrair_dados_btg(caminho_arquivo, cpf_cliente=None):
    print(f"\n" + "="*50)
    print(f"[BTG_PARSER] INICIANDO ROBÔ BTG V3 (POWERED BY GEMINI AI)")
    print(f"="*50)
    try:
        # 1. Leitura Bruta (Pypdf apenas extrai a maçaroca de texto)
        leitor = PdfReader(caminho_arquivo)
        texto_original = leitor.pages[-1].extract_text()
        
        if "BTG PACTUAL" not in texto_original.upper():
            print("[BTG_PARSER] ERRO: O PDF não pertence ao BTG Pactual.")
            return None

        # 2. Sanitização (Blindagem LGPD)
        print("[BTG_PARSER] Sanitizando dados sensíveis (LGPD)...")
        texto_seguro = sanitizar_texto(texto_original, cpf_cliente)

        # 3. Configuração e Chamada da API do Gemini
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise Exception("Chave GEMINI_API_KEY não encontrada no ambiente (.env ou Render).")
        
        genai.configure(api_key=api_key)
        
        # Utilizamos o modelo 1.5 Flash (Gratuito, ultra-rápido e excelente para extração)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = """
        Você é um analista financeiro extraindo dados de uma nota de corretagem da BTG Pactual.
        O texto extraído do PDF está muito bagunçado, com números e letras grudados, devido à quebra de colunas.
        
        Encontre exatamente 3 informações financeiras da nota:
        1. Data do Pregão (no formato DD/MM/AAAA).
        2. Valor Bruto do Day Trade (Geralmente atrelado ao termo 'Ajuste day trade').
        3. Total Líquido da Nota (Geralmente o último valor financeiro que aparece no final do documento).
        
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
        
        print("[BTG_PARSER] Enviando texto mascarado para o Cérebro IA...")
        response = model.generate_content([prompt, texto_seguro])
        
        # Limpeza do retorno JSON (Remove markdowns se a IA adicionar)
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
        
        print(f"    -> [GEMINI] Data Encontrada: {data_pregao}")
        print(f"    -> [GEMINI] Bruto Extraído: {v_bruto}")
        print(f"    -> [GEMINI] Líquido Extraído: {v_liquido_pregao}")

        # ==================================================
        # 4. Vacina Matemática e Fechamento (Lógica Offline)
        # Nenhuma matemática da DW Capital vai para a nuvem.
        # ==================================================
        print("\n  [MATEMÁTICA] --- INICIANDO CÁLCULOS OFF-LINE DA MESA ---")
        
        # A vacina infalível: Bruto - Líquido revela todas as taxas e impostos ocultos
        v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
        
        if v_custos_unificados < 0:
            print(f"    [!] Anomalia BTG: Custos negativos detectados ({v_custos_unificados}). O PDF inverteu o sinal de loss.")
            v_liquido_pregao = -abs(v_liquido_pregao)
            v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
            print(f"    [!] Correção aplicada. Novo Líquido: {v_liquido_pregao} | Novos Custos: {v_custos_unificados}")
            
        print(f"    Custos Calculados: Bruto ({v_bruto}) - Líquido ({v_liquido_pregao}) = {v_custos_unificados}")
        
        if v_liquido_pregao > 0:
            v_irrf_19 = round(v_liquido_pregao * 0.19, 2)
            print(f"    Fórmula: IRRF 19% = {v_liquido_pregao} * 0.19 = {v_irrf_19}")
        else:
            v_irrf_19 = 0.0
            print(f"    Fórmula: IRRF 19% = 0.00 (Pregão foi LOSS ou Zero)")
            
        v_liquido_dia = round(v_liquido_pregao - v_irrf_19, 2)
        print(f"    Fórmula: Líquido Real = {v_liquido_pregao} - {v_irrf_19} = {v_liquido_dia}")
        
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
            'taxas_b3': v_custos_unificados,
            'irrf_1': 0.0, # Zerado no banco, pois os custos unificados já engolem B3 + IR1%
            'liquido_pregao': v_liquido_pregao,
            'irrf_19': v_irrf_19,
            'liquido_dia': v_liquido_dia,
            'repasse_dw': v_repasse
        }

    except Exception as e:
        print(f"[BTG_PARSER] Erro crítico na extração inteligente: {str(e)}")
        return None