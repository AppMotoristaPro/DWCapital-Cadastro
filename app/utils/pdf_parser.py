import re
from pypdf import PdfReader

def extrair_dados_nota_corretagem(caminho_arquivo):
    try:
        print(f"--- [ROBÔ] INICIANDO LEITURA DO PDF: {caminho_arquivo} ---")
        leitor = PdfReader(caminho_arquivo)
        
        # Extrai a Data do Pregão
        texto_primeira_pagina = leitor.pages[0].extract_text()
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_primeira_pagina)
        data_pregao = match_data.group(1) if match_data else None
        print(f"[LOG] Data identificada no topo: {data_pregao}")

        # Extrai valores financeiros das páginas finais (onde fica o resumo)
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
            original = resultado
            # Remove sufixos e espaços
            resultado = resultado.strip().upper().replace('C', '').replace('D', '').replace(' ', '')
            
            # Lógica para ponto ou vírgula
            if ',' in resultado:
                val = resultado.replace('.', '').replace(',', '.')
            else:
                val = resultado
            
            try:
                final = float(val)
                print(f"[LOG] Limpeza: '{original}' -> '{val}' -> {final}")
                return final
            except:
                print(f"[ERROR] Falha ao converter valor: '{val}'")
                return 0.0

        def extrair_valor_linha(nome_campo, padrao, texto):
            # Regex aceita tanto .00 quanto ,00
            regex_valor = r"(\d[\d\.,]*[\.,]\d{2})"
            match = re.search(padrao + r".*?" + regex_valor, texto, re.IGNORECASE | re.MULTILINE)
            if match:
                linha = match.group(0)
                numeros = re.findall(regex_valor, linha)
                if numeros:
                    valor = limpar_valor(numeros[-1])
                    print(f"[LOG SUCCESS] {nome_campo}: {valor} (Encontrado na linha: '{linha.strip()}')")
                    return valor
            print(f"[LOG WARNING] {nome_campo} não encontrado.")
            return 0.0

        # 1. Valor Líquido (O que entra/sai da conta)
        print("[LOG] Procurando Líquido da Nota...")
        v_liquido_pregao = 0.0
        # Mapeia as nomenclaturas da B3 e Genial
        match_liquido = re.search(r"(L[ií]quido para.*|L[ií]quido da nota.*|Total l[ií]quido da nota.*)", texto_completo, re.IGNORECASE)
        if match_liquido:
            linha_liq = match_liquido.group(0)
            numeros = re.findall(r"(\d[\d\.,]*[\.,]\d{2})", linha_liq)
            if numeros:
                v_liquido_pregao = limpar_valor(numeros[-1])
                print(f"[LOG SUCCESS] Líquido Nota: {v_liquido_pregao}")

        # 2. Imposto e Taxas
        v_irrf_1 = extrair_valor_linha("IRRF 1%", r"(I\.?R\.?R\.?F\.?.*?Day\s*Trade|IRRF.*?Proje[çc][ãa]o)", texto_completo)
        
        taxa_liquidacao = extrair_valor_linha("Taxa Liquidação", r"Taxas? de liquida[çc][ãa]o", texto_completo)
        taxa_registro = extrair_valor_linha("Taxa Registro", r"(Taxa de [rR]egistro|Taxa registro BM&F)", texto_completo)
        emolumentos = extrair_valor_linha("Emolumentos", r"(Emolumentos|Taxas? BM&F|Taxa de termo/op[çc][õo]es/emolumentos)", texto_completo)
        
        v_taxas_b3 = taxa_liquidacao + taxa_registro + emolumentos

        # --- CÁLCULOS FINAIS ---
        v_bruto = v_liquido_pregao + v_irrf_1 + v_taxas_b3
        base_calculo_ir = v_bruto - v_taxas_b3
        v_irrf_19 = base_calculo_ir * 0.19 if base_calculo_ir > 0 else 0.0
        v_liquido_dia = v_liquido_pregao - v_irrf_19
        v_repasse = v_liquido_dia * 0.30 if v_liquido_dia > 0 else 0.0

        print(f"--- [RESUMO EXTRAÇÃO] ---")
        print(f"Bruto: {v_bruto} | Taxas B3: {v_taxas_b3} | IRRF 1%: {v_irrf_1} | Repasse: {v_repasse}")
        print(f"-------------------------")

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
        print(f"[FATAL ERROR] Erro no Parser: {str(e)}")
        return None

