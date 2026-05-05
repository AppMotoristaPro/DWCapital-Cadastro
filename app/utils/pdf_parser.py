import re
from pypdf import PdfReader

def extrair_dados_nota_corretagem(caminho_arquivo):
    try:
        print(f"--- [ROBÔ] INICIANDO LEITURA DO PDF: {caminho_arquivo} ---")
        leitor = PdfReader(caminho_arquivo)
        
        # FOCA EXCLUSIVAMENTE NA ÚLTIMA PÁGINA (Ignora todas as anteriores)
        ultima_pagina = leitor.pages[-1]
        texto_completo = ultima_pagina.extract_text()
        
        print(f"--- [DEBUG] CONTEÚDO BRUTO DA ÚLTIMA PÁGINA ---")
        print(texto_completo)
        print("--------------------------------------------------")

        # Extrai a Data do Pregão lendo o cabeçalho da última página
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo)
        data_pregao = match_data.group(1) if match_data else None
        print(f"[LOG] Data identificada na última página: {data_pregao}")

        def limpar_valor(resultado):
            if not resultado: return 0.0
            # Remove letras (C/D), sinais e espaços, mantendo apenas dígitos, pontos e vírgulas
            resultado = re.sub(r'[^\d,.]', '', resultado)
            
            # Lógica de conversão flexível (BR vs US)
            if ',' in resultado:
                # Padrão Brasileiro: 1.020,00 -> 1020.00
                val = resultado.replace('.', '').replace(',', '.')
            else:
                # Padrão Americano/Genial: 9.01 -> 9.01
                val = resultado
            
            try:
                return float(val)
            except:
                return 0.0

        # NOVA LÓGICA: Busca por Posição (Índice)
        def extrair_por_posicao(nome_campo, padrao, texto, posicao):
            # Busca a palavra e pega um bloco de texto depois (200 caracteres para cobrir a linha de baixo)
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                bloco_depois = texto[match.end():match.end()+200]
                # Regex para capturar todos os números no formato monetário que aparecem depois
                numeros = re.findall(r"(\d[\d\.,]*[\.,]\d{2})", bloco_depois)
                
                if numeros and len(numeros) >= posicao:
                    # 'posicao - 1' porque o array em Python começa no 0 (ex: 1º valor é índice 0)
                    valor_str = numeros[posicao - 1]
                    valor = limpar_valor(valor_str)
                    print(f"[LOG SUCCESS] {nome_campo} (Posição {posicao}): {valor} | Lista lida: {numeros}")
                    return valor
                else:
                    print(f"[LOG WARNING] {nome_campo}: Palavra encontrada, mas não achou o {posicao}º número. Lidos: {numeros}")
            else:
                print(f"[LOG WARNING] {nome_campo}: Palavra-chave '{padrao}' não encontrada.")
            return 0.0

        # 1. Valor Bruto (Valor dos Negócios) -> 1º número após a palavra
        v_bruto = extrair_por_posicao("Valor Bruto", r"Valor dos negócios", texto_completo, 1)

        # 2. IRRF "Dedo-Duro" 1% -> 2º número após a linha de impostos (IRRF Day Trade / Taxas BM&F)
        v_irrf_1 = extrair_por_posicao("IRRF 1%", r"(IRRF Day Trade|Taxas BM&F \( emol\+f\.gar\))", texto_completo, 2)

        # 3. Taxas B3 (Total das despesas) -> 4º número após a palavra "Total das despesas"
        v_taxas_b3 = extrair_por_posicao("Taxas B3", r"Total das despesas", texto_completo, 4)


        # ==========================================
        # A MATEMÁTICA GENIAL (Cálculos em Cascata)
        # ==========================================
        
        # 4. Valor Líquido do Pregão
        v_liquido_pregao = v_bruto - v_taxas_b3 - v_irrf_1

        # 5. IRRF DARF (19%) sobre o lucro
        v_irrf_19 = v_liquido_pregao * 0.19 if v_liquido_pregao > 0 else 0.0

        # 6. Valor Líquido do Dia
        v_liquido_dia = v_liquido_pregao - v_irrf_19

        # 7. Repasse DW Capital (30%)
        v_repasse = v_liquido_dia * 0.30 if v_liquido_dia > 0 else 0.0


        print(f"--- [RESUMO FINAL DA MATEMÁTICA] ---")
        print(f"Bruto: R$ {v_bruto} | Taxas B3: R$ {v_taxas_b3} | IRRF 1%: R$ {v_irrf_1}")
        print(f"Líquido Pregão (Conta): R$ {v_liquido_pregao}")
        print(f"IRRF 19%: R$ {v_irrf_19} | Líquido Dia: R$ {v_liquido_dia}")
        print(f"Repasse DW (30%): R$ {v_repasse}")
        print(f"------------------------------------")

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
        print(f"[FATAL ERROR] Erro crítico no robô: {str(e)}")
        return None

