import re
from pypdf import PdfReader

def extrair_dados_nota_corretagem(caminho_arquivo):
    try:
        leitor = PdfReader(caminho_arquivo)
        
        # Extrai a Data do Pregão
        texto_primeira_pagina = leitor.pages[0].extract_text()
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_primeira_pagina)
        data_pregao = match_data.group(1) if match_data else None

        # Extrai valores financeiros das páginas finais
        texto_completo = ""
        # Lemos as 3 últimas páginas para garantir o resumo (Genial usa a folha 4)
        paginas_finais = leitor.pages[-3:] if len(leitor.pages) > 2 else leitor.pages
        for pagina in paginas_finais:
            texto_completo += pagina.extract_text() + "\n"

        # NOVA FUNÇÃO DE LIMPEZA: Detecta ponto ou vírgula decimal
        def limpar_valor(resultado):
            if not resultado: return 0.0
            # Remove sufixos como 'C', 'D' ou '.' no final
            resultado = resultado.strip().upper().replace('C', '').replace('D', '')
            
            # Se tem vírgula, o ponto é milhar e a vírgula é decimal (Padrão BR)
            if ',' in resultado:
                val = resultado.replace('.', '').replace(',', '.')
            else:
                # Se não tem vírgula, o ponto já é o decimal (Padrão Americano/Genial)
                val = resultado
            
            try:
                return float(val)
            except:
                return 0.0

        # FUNÇÃO DE BUSCA: Aceita .00 ou ,00 como final de valor
        def extrair_valor_linha(padrao, texto):
            # Regex agora aceita ponto ou vírgula antes dos dois dígitos finais
            regex_valor = r"(\d[\d\.,]*[\.,]\d{2})"
            match = re.search(padrao + r".*?" + regex_valor, texto, re.IGNORECASE | re.MULTILINE)
            if match:
                linha = match.group(0)
                numeros = re.findall(regex_valor, linha)
                if numeros:
                    return limpar_valor(numeros[-1])
            return 0.0

        # 1. Valor Líquido da Nota (O valor que realmente entra/sai da conta)
        v_liquido_pregao = 0.0
        match_liquido_termo = re.search(r"(L[ií]quido para.*|L[ií]quido da nota.*|Total l[ií]quido da nota.*)", texto_completo, re.IGNORECASE)
        if match_liquido_termo:
            numeros = re.findall(r"(\d[\d\.,]*[\.,]\d{2})", match_liquido_termo.group(0))
            if numeros:
                v_liquido_pregao = limpar_valor(numeros[-1])

        # 2. IRRF 1% (Mapeia Genial: "IRRF Day Trade (Projeção)")
        v_irrf_1 = extrair_valor_linha(r"(I\.?R\.?R\.?F\.?.*?Day\s*Trade|IRRF.*?Proje[çc][ãa]o)", texto_completo)
        
        # 3. Taxas B3 (Mapeia Genial: "Taxa registro BM&F" e "Taxas BM&F")
        taxa_liquidacao = extrair_valor_linha(r"Taxas? de liquida[çc][ãa]o", texto_completo)
        taxa_registro = extrair_valor_linha(r"(Taxa de [rR]egistro|Taxa registro BM&F)", texto_completo)
        
        # Emolumentos (Mapeia Genial: "Taxas BM&F (emol+fgar)")
        emolumentos = extrair_valor_linha(r"(Emolumentos|Taxas? BM&F|Taxa de termo/op[çc][õo]es/emolumentos)", texto_completo)
        
        v_taxas_b3 = taxa_liquidacao + taxa_registro + emolumentos

        # --- CÁLCULOS PADRÃO DW CAPITAL ---
        
        # Valor Bruto (Soma do líquido com o que foi descontado)
        v_bruto = v_liquido_pregao + v_irrf_1 + v_taxas_b3

        # Base para o IR de 19%
        base_calculo_ir = v_bruto - v_taxas_b3
        v_irrf_19 = base_calculo_ir * 0.19 if base_calculo_ir > 0 else 0.0
        
        # Valor Líquido Real do Cliente (Dia)
        v_liquido_dia = v_liquido_pregao - v_irrf_19

        # Repasse DW Capital (30%)
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
        print(f"Erro no Parser: {e}")
        return None

