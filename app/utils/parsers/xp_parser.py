import os
import re
import json
import io
import pikepdf
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

def extrair_dados_xp(caminho_arquivo, cpf_cliente, senha_manual=None):
    print(f"\n" + "="*50)
    print(f"[XP_PARSER] INICIANDO ROBÔ XP V4 (DECRYPT + POWERED BY GROQ & LLAMA 3)")
    print(f"="*50)
    try:
        if senha_manual:
            senha_final = str(senha_manual).strip()
        else:
            cpf_limpo = ''.join(filter(str.isdigit, str(cpf_cliente)))
            senha_final = cpf_limpo[-3:] if len(cpf_limpo) >= 3 else ""
        
        texto_full = ""
        try:
            with pikepdf.open(caminho_arquivo, password=senha_final) as pdf_trancado:
                buffer_limpo = io.BytesIO()
                pdf_trancado.save(buffer_limpo)
                buffer_limpo.seek(0)
            
            with open(caminho_arquivo, "wb") as f_out:
                f_out.write(buffer_limpo.getvalue())

            leitor = PdfReader(buffer_limpo)
            texto_full = leitor.pages[-1].extract_text()
                
        except pikepdf.PasswordError:
            raise Exception("SENHA_INCORRETA")
        except Exception:
            try:
                leitor = PdfReader(caminho_arquivo)
                if leitor.is_encrypted:
                    leitor.decrypt(senha_final)
                texto_full = leitor.pages[-1].extract_text()
            except Exception:
                raise Exception("SENHA_INCORRETA")

        if "XP INVESTIMENTOS" not in texto_full.upper():
            return None

        # CORTE EXTREMO: Pega apenas Cabeçalho (600 chars) e Rodapé (1000 chars)
        if len(texto_full) > 1600:
            texto_original = texto_full[:600] + "\n\n... [OPERAÇÕES DELETADAS] ...\n\n" + texto_full[-1000:]
        else:
            texto_original = texto_full
        
        print("[XP_PARSER] Senha validada. Texto reduzido ao máximo. Sanitizando (LGPD)...")
        texto_seguro = sanitizar_texto(texto_original, cpf_cliente)

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise Exception("Chave GROQ_API_KEY não encontrada.")
        
        client = Groq(api_key=api_key)
        modelo_alvo = "llama-3.3-70b-versatile"
        
        print("\n  [GROQ DIAGNÓSTICO] Verificando ambiente de integração...")
        print(f"    -> Modelo validado e acionado para leitura: {modelo_alvo}\n")
        
        prompt = """
        Você é um auditor financeiro especialista na extração de dados de notas de corretagem da XP Investimentos.
        O texto recebido contém apenas o cabeçalho e o rodapé do PDF. A letra 'D' pode estar colada no número (ex: 820,00D).
        
        Encontre 3 informações exatas:
        1. Data do Pregão (DD/MM/AAAA).
        2. Valor Bruto: Procure por 'Ajuste day trade' ou 'Valor dos negócios'. Pegue o valor não zerado.
        3. Total Líquido: Procure por 'Total líquido da nota'.
        
        REGRA MATEMÁTICA CRÍTICA:
        Sempre verifique se há um 'D' (Débito) ou 'C' (Crédito) atrelado ao valor. Se houver 'D', o valor DEVE TER SINAL NEGATIVO (-).
        
        Retorne EXCLUSIVAMENTE um JSON válido. Use o campo 'raciocinio' para explicar a captura antes dos valores finais.
        Estrutura obrigatória de exemplo:
        {
            "raciocinio": "Achei Ajuste day trade 820,00D (Sinal negativo). O líquido é 847,00 com D (Sinal negativo).",
            "data_pregao": "06/05/2026",
            "bruto": -820.00,
            "liquido_nota": -847.00
        }
        """
        
        print("  [GROQ REQUEST] Despachando nota mascarada para a nuvem Groq...")
        print("  --- INÍCIO DO TEXTO ENVIADO (MÁXIMO ENXUTO) ---")
        print(texto_seguro)
        print("  --- FIM DO TEXTO ENVIADO ---\n")

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
        
        print("  [GROQ RESPONSE] Resposta bruta devolvida pela IA:")
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