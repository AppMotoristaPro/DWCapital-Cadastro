import re
from pypdf import PdfReader

def extrair_dados_nota_corretagem(caminho_arquivo):
    try:
        print(f"--- [ROBÔ] INICIANDO LEITURA DO PDF: {caminho_arquivo} ---")
        leitor = PdfReader(caminho_arquivo)
        
        # Extrai a Data do Pregão (Sempre na primeira página)
        texto_primeira_pagina = leitor.pages[0].extract_text()
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_primeira_pagina)
        data_pregao = match_data.group(1) if match_data else None
        print(f"[LOG] Data identificada: {data_pregao}")

        # Extrai conteúdo das páginas de resumo (geralmente as últimas)
        texto_completo = ""
        paginas_finais = leitor.pages[-3:] if len(leitor.pages) > 2 else leitor.pages
        for i, pagina in enumerate(paginas_finais):
            conteudo = pagina.extract_text()
            texto_completo += conteudo + "\n"
            print(f"--- [DEBUG] CONTEÚDO BRUTO PÁGINA FINAL {i+1} ---")
            print(conteudo)
            print("--------------------------------------------------")

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

        def extrair_valor_flexivel(nome_campo, padrao, texto):
            # Procura a palavra-chave e captura um bloco de 100 caracteres à frente
            # O modificador [\s\S] permite que a busca atravesse quebras de linha
            match = re.search(padrao + r"[\s\S]{0,100}?", texto, re.IGNORECASE)
            if match:
                bloco_depois = texto[match.end():match.end()+120]
                # Regex para capturar números no formato monetário (ex: 1.234,56 ou 12.34)
                numeros = re.findall(r"(\d[\d\.,]*[\.,]\d{2})", bloco_depois)
                if numeros:
                    # Para Genial (multilinhas), pegamos o primeiro número que segue o rótulo
                    valor = limpar_valor(numeros[0])
                    print(f"[LOG SUCCESS] {nome_campo}: {valor}")
                    return valor
            print(f"[LOG WARNING] {nome_campo} não encontrado no bloco.")
            return 0.0

        # 1. Valor Líquido da Nota (Total que entra/sai da conta)
        v_liquido_pregao = extrair_valor_flexivel(
            "Líquido Nota", 
            r"(Total l[ií]quido da nota|L[ií]quido da nota|Total l[ií]quido \(#\))", 
            texto_completo
        )

        # 2. IRRF 1% (Projeção)
        v_irrf_1 = extrair_valor_flexivel(
            "IRRF 1%", 
            r"(I\.?R\.?R\.?F\.?.*?Day\s*Trade|IRRF.*?Proje[çc][ãa]o)", 
            texto_completo
        )
        
        # 3. Taxas B3 (Soma de Liquidação, Registro e Emolumentos)
        taxa_liquidacao = extrair_valor_flexivel("Taxa Liquidação", r"Taxas? de liquida[çc][ãa]o", texto_completo)
        taxa_registro = extrair_valor_flexivel("Taxa Registro", r"(Taxa de [rR]egistro|Taxa registro BM&F)", texto_completo)
        emolumentos = extrair_valor_flexivel("Emolumentos", r"(Emolumentos|Taxas? BM&F|Taxa de termo/op[çc][õo]es/emolumentos)", texto_completo)
        
        v_taxas_b3 = taxa_liquidacao + taxa_registro + emolumentos

        # --- CÁLCULOS PADRÃO DW CAPITAL ---
        # Bruto = Líquido da nota + descontos (IRRF 1% e Taxas B3)
        v_bruto = v_liquido_pregao + v_irrf_1 + v_taxas_b3

        # Base para o IR 19% e Valor do DARF
        base_calculo_ir = v_bruto - v_taxas_b3
        v_irrf_19 = base_calculo_ir * 0.19 if base_calculo_ir > 0 else 0.0
        
        # Valor Líquido Real (Dia)
        v_liquido_dia = v_liquido_pregao - v_irrf_19

        # Repasse DW Capital (30%)
        v_repasse = v_liquido_dia * 0.30 if v_liquido_dia > 0 else 0.0

        print(f"--- [RESUMO FINAL DA EXTRAÇÃO] ---")
        print(f"Bruto: {v_bruto} | Taxas B3: {v_taxas_b3} | IRRF 1%: {v_irrf_1} | Repasse: {v_repasse}")
        print(f"----------------------------------")

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

