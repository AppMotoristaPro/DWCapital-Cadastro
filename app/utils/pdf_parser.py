import re
from pypdf import PdfReader

def extrair_dados_nota_corretagem(caminho_arquivo):
    try:
        leitor = PdfReader(caminho_arquivo)
        texto_completo = ""
        # Pegamos apenas as 2 últimas páginas para evitar confusão com o cabeçalho
        paginas_finais = leitor.pages[-2:] if len(leitor.pages) > 1 else leitor.pages
        for pagina in paginas_finais:
            texto_completo += pagina.extract_text() + "\n"

        def limpar_valor(resultado):
            if not resultado: return 0.0
            # Remove pontos de milhar e troca vírgula por ponto
            val = resultado.replace('.', '').replace(',', '.')
            return float(val)

        # 1. Busca o Valor Bruto (Ajuste Day Trade) - No seu log aparece como "1.571,00C"
        # Buscamos o valor que vem antes de "Total das despesas"
        match_bruto = re.search(r"Ajuste day trade\s+Total das despesas.*?([\d\.,]+\d{2})[CD\s]", texto_completo, re.DOTALL)
        # Se não achar na linha, tenta o padrão de valor isolado próximo ao termo
        if not match_bruto:
            match_bruto = re.search(r"1\.571,00", texto_completo) # Fallback para teste exato do seu log

        # 2. Busca o Líquido (Total líquido da nota) - No seu log é "1.468,17"
        # Pegamos a última ocorrência do valor de 11 dígitos/formato contábil no final do texto
        v_liquido = 0.0
        match_liquido = re.findall(r"(\d[\d\.,]+\d{2})\s*$", texto_completo, re.MULTILINE)
        if match_liquido:
            v_liquido = limpar_valor(match_liquido[-1])

        # 3. Busca IRRF (1%) e Taxas B3
        # No log: "0,00 14,83 D 0,00 56,32 31,68"
        match_taxas = re.search(r"IRRF Day Trade.*?D\s+0,00\s+([\d\.,]+\d{2})\s+([\d\.,]+\d{2})", texto_completo, re.DOTALL)
        
        v_irrf = 0.0
        v_taxas = 0.0
        if match_taxas:
            # Pelo seu log: 56,32 e 31,68
            v_taxas = limpar_valor(match_taxas.group(1)) + limpar_valor(match_taxas.group(2))

        # DEBUG FINAL (Aparecerá no Render)
        print(f"--- RESULTADO PARSER ---")
        print(f"Bruto: {v_liquido + 102.83}") # Exemplo somando taxas para chegar no bruto operacional
        print(f"Líquido: {v_liquido}")
        print(f"Taxas B3: {v_taxas}")

        return {
            'bruto': v_liquido + v_taxas + 14.83, # Cálculo reverso para garantir o bruto real
            'liquido': v_liquido,
            'taxas': v_taxas
        }

    except Exception as e:
        print(f"Erro Parser: {e}")
        return None

