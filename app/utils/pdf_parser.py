import re
from pypdf import PdfReader

def extrair_dados_nota_corretagem(caminho_arquivo):
    try:
        leitor = PdfReader(caminho_arquivo)
        # Pega o texto das últimas páginas (onde ficam os resumos)
        texto_completo = ""
        for i in range(len(leitor.pages)-1, -1, -1):
            texto_completo += leitor.pages[i].extract_text() or ""
            if "Total líquido da nota" in texto_completo: break

        # Regex flexível para capturar 1.234,56 ou 1234.56
        def extrair_valor(padrao, texto):
            m = re.search(padrao, texto, re.IGNORECASE | re.DOTALL)
            if not m: return 0.0
            val_str = m.group(1).replace('.', '').replace(',', '.')
            val = float(val_str)
            if 'liquido' in padrao and m.group(2).upper() == 'D': val = -val
            return val

        # Ajuste Day Trade é o faturamento operacional (Bruto para a DW)
        bruto = extrair_valor(r"Ajuste day trade.*?([\d\.,]+\d{2})", texto_completo)
        liquido = extrair_valor(r"Total l[ií]quido da nota.*?([\d\.,]+\d{2})\s*([CD])", texto_completo)
        irrf_1 = extrair_valor(r"IRRF Day Trade.*?([\d\.,]+\d{2})", texto_completo)
        
        t_bmf = extrair_valor(r"Taxas BM&F \(emol\+fgar\).*?([\d\.,]+\d{2})", texto_completo)
        t_reg = extrair_valor(r"Taxa registro BM&F.*?([\d\.,]+\d{2})", texto_completo)

        return {
            'bruto': bruto,
            'liquido': liquido,
            'irrf_1': irrf_1,
            'taxas_b3': t_bmf + t_reg
        }
    except Exception as e:
        print(f"Erro PDF: {e}")
        return None

