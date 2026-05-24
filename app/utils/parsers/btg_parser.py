import os
import re
import json
from groq import Groq
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
    print(f"[BTG_PARSER] INICIANDO ROBÔ BTG V4 (POWERED BY GROQ & FALLBACKS)")
    print(f"="*50)
    try:
        leitor = PdfReader(caminho_arquivo)
        texto_full = leitor.pages[-1].extract_text()
        print("[BTG_PARSER] Texto extraído. Aplicando corte extremo para a IA...")

        if "BTG PACTUAL" not in texto_full.upper():
            print("[BTG_PARSER] ERRO: O PDF não pertence ao BTG Pactual.")
            raise Exception("PDF_INCOMPATIVEL: O arquivo enviado não pertence ao BTG Pactual.")

        # CORTE EXTREMO: Pega apenas Cabeçalho (600 chars) e Rodapé (1000 chars)
        if len(texto_full) > 1600:
            texto_original = texto_full[:600] + "\n\n... [OPERAÇÕES DELETADAS] ...\n\n" + texto_full[-1000:]
        else:
            texto_original = texto_full

        print("[BTG_PARSER] Sanitizando dados sensíveis (LGPD)...")
        texto_seguro = sanitizar_texto(texto_original, cpf_cliente)

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise Exception("Chave GROQ_API_KEY não encontrada no ambiente (.env ou Render).")
        
        client = Groq(api_key=api_key)
        
        prompt = """
        Você é um auditor financeiro especialista na extração de dados de notas de corretagem da BTG Pactual.
        O texto recebido contém apenas o cabeçalho e o rodapé do PDF.
        
        Encontre 3 informações exatas:
        1. Data do Pregão (DD/MM/AAAA).
        2. Valor Bruto: Procure por 'Ajuste day trade' ou 'Valor dos negócios'. Pegue o valor não zerado.
        3. Total Líquido: Procure por 'Total líquido da nota' (Geralmente no final do documento).
        
        REGRA MATEMÁTICA CRÍTICA SOBRE SINAIS:
        A letra 'C' significa CRÉDITO (POSITIVO). A letra 'D' significa DÉBITO (NEGATIVO).
        Verifique ATENTAMENTE a letra que está colada ou logo após o número. 
        Se houver 'C', o valor é ESTRITAMENTE POSITIVO.
        Só use sinal negativo (-) se houver certeza da letra 'D' atrelada ao valor. Não assuma ou invente 'D' onde existe 'C'.
        
        Retorne EXCLUSIVAMENTE um JSON válido. Use o campo 'raciocinio' para explicar a captura (mostre o número e a letra que encontrou).
        Estrutura obrigatória de exemplo:
        {
            "raciocinio": "Achei Ajuste day trade 598,00 C (Positivo). O líquido é 554,96 C (Positivo).",
            "data_pregao": "06/05/2026",
            "bruto": 598.00,
            "liquido_nota": 554.96
        }
        """
        
        print("  [GROQ REQUEST] Despachando nota mascarada para a nuvem Groq...")
        
        # ROLETA DE MODELOS (FALLBACK) PARA DRIBLAR O LIMITE DE TOKENS (ERROR 429)
        modelos_para_tentar = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]
        texto_json = None
        
        for modelo_alvo in modelos_para_tentar:
            try:
                print(f"  [GROQ DIAGNÓSTICO] Tentando alocação no modelo: {modelo_alvo}...")
                response = client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": texto_seguro}
                    ],
                    model=modelo_alvo,
                    temperature=0.0,
                    response_format={"type": "json_object"}
                )
                texto_json = response.choices[0].message.content.strip()
                print(f"    -> Sucesso no modelo {modelo_alvo}!")
                break # Sai do loop se o modelo funcionar
                
            except Exception as e:
                print(f"    [!] Falha no modelo {modelo_alvo}: {str(e)}")
                if "429" in str(e) or "rate limit" in str(e).lower():
                    print("    -> Cota diária excedida. Pulando para o modelo reserva...")
                    continue # Tenta o próximo modelo
                else:
                    raise e # Se for outro erro (como falha de API key), aborta tudo.
                    
        if not texto_json:
            raise Exception("Limites diários excedidos em todos os modelos de fallback do Groq. Tente novamente mais tarde.")

        print("\n  [GROQ RESPONSE] Resposta bruta devolvida pela IA:")
        print("  --- INÍCIO DO RETORNO ---")
        print(texto_json)
        print("  --- FIM DO RETORNO ---\n")
        
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
            print(f"    [!] Anomalia BTG: Custos negativos detectados ({v_custos_unificados}). O PDF ou a IA inverteu os sinais.")
            
            # FILTRO ANTI-ALUCINAÇÃO
            # Se Custos deu negativo e a IA mandou valores negativos, ela transformou um GAIN em LOSS indevidamente.
            if v_bruto < 0 and v_liquido_pregao < 0:
                print("    [!] A IA negativou indevidamente um Gain. Forçando valores para POSITIVO.")
                v_bruto = abs(v_bruto)
                v_liquido_pregao = abs(v_liquido_pregao)
                v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
                
            # Tratamento de Loss verdadeiro onde a IA esqueceu os sinais
            elif abs(v_liquido_pregao) > abs(v_bruto):
                v_bruto = -abs(v_bruto)
                v_liquido_pregao = -abs(v_liquido_pregao)
                v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
                print(f"    [!] Correção Dupla (Loss) aplicada. Novo Bruto: {v_bruto} | Novo Líquido: {v_liquido_pregao}")
                
            else:
                v_liquido_pregao = -abs(v_liquido_pregao)
                v_custos_unificados = round(v_bruto - v_liquido_pregao, 2)
                print(f"    [!] Correção Parcial aplicada. Novo Líquido: {v_liquido_pregao}")
                
        # Garante segurança matemática absoluta (taxa da b3 e corretagem nunca são negativas)
        v_custos_unificados = abs(v_custos_unificados)
            
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
        if "PDF_INCOMPATIVEL" in str(e):
            raise e
        return None

