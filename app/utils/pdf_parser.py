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
        # Algumas corretoras empurram o resumo para a antepenúltima página se o dia for muito cheio.
        # Por segurança, vamos ler até as 3 últimas páginas.
        paginas_finais = leitor.pages[-3:] if len(leitor.pages) > 2 else leitor.pages
        for pagina in paginas_finais:
            texto_completo += pagina.extract_text() + "\n"

        def limpar_valor(resultado):
            if not resultado: return 0.0
            val = resultado.replace('.', '').replace(',', '.')
            return float(val)

        # NOVA FUNÇÃO BLINDADA PARA XP, GENIAL E BTG
        def extrair_valor_linha(padrao, texto):
            # Encontra a frase e captura tudo até o último número da linha
            match = re.search(padrao + r".*?(\d[\d\.,]*,\d{2})", texto, re.IGNORECASE | re.MULTILINE)
            if match:
                linha = match.group(0)
                # Extrai todos os valores formatados como dinheiro (ex: 1.500,00 ou 5,32)
                numeros = re.findall(r"(\d[\d\.,]*,\d{2})", linha)
                if numeros:
                    # Nas notas SINACOR (XP, BTG, Genial), o último número da linha é sempre o valor descontado
                    return limpar_valor(numeros[-1])
            return 0.0

        # 1. Extração do Valor Líquido do Pregão
        v_liquido_pregao = 0.0
        # Tenta pegar pela nomenclatura oficial do Resumo Financeiro
        match_liquido_termo = re.search(r"(L[ií]quido para.*|L[ií]quido da nota.*)", texto_completo, re.IGNORECASE)
        if match_liquido_termo:
            numeros = re.findall(r"(\d[\d\.,]*,\d{2})", match_liquido_termo.group(0))
            if numeros:
                v_liquido_pregao = limpar_valor(numeros[-1])
        else:
            # Fallback de segurança: pega o último número solto no final do documento
            match_liquido = re.findall(r"(\d[\d\.,]*,\d{2})\s*$", texto_completo, re.MULTILINE)
            if match_liquido:
                v_liquido_pregao = limpar_valor(match_liquido[-1])

        # 2. Extração das Taxas B3 e IRRF (Mapeando variações das corretoras)
        # Cobre "I.R.R.F. Day Trade", "IRRF s/ operações Day Trade", etc.
        v_irrf_1 = extrair_valor_linha(r"(I\.?R\.?R\.?F\.?.*?Day\s*Trade|IRRF\s*s/\s*opera[çc][õo]es.*?Day)", texto_completo)
        
        # Cobre "Taxa de liquidação", "Taxas de liquidação", etc.
        taxa_liquidacao = extrair_valor_linha(r"Taxas? de liquida[çc][ãa]o", texto_completo)
        
        # Cobre "Emolumentos" puro ou a junção "Taxa de termo/opções/emolumentos" (muito comum na XP e Rico)
        emolumentos = extrair_valor_linha(r"(Emolumentos|Taxa de termo/op[çc][õo]es/emolumentos)", texto_completo)
        
        # Cobre "Taxa de Registro" ou "Taxa de registro da BMF"
        taxa_registro = extrair_valor_linha(r"Taxa de [rR]egistro", texto_completo)
        
        v_taxas_b3 = taxa_liquidacao + emolumentos + taxa_registro

        # --- CÁLCULOS DW CAPITAL ---

        # Valor Bruto
        v_bruto = v_liquido_pregao + v_irrf_1 + v_taxas_b3

        # Base do IR 19% e Valor do DARF
        base_calculo_ir = v_bruto - v_taxas_b3
        v_irrf_19 = base_calculo_ir * 0.19 if base_calculo_ir > 0 else 0.0
        
        # Valor Líquido do Cliente (Dia)
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

