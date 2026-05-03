import re
from pypdf import PdfReader

def extrair_dados_nota_corretagem(caminho_arquivo):
    try:
        leitor = PdfReader(caminho_arquivo)
        texto_completo = "".join([p.extract_text() or "" for p in leitor.pages])

        # Padrões baseados na Nota da Genial
        padroes = {
            'bruto': r"Valor dos neg[oó]cios.*?([\d\.]+,\d{2})",
            'liquido': r"Total l[ií]quido da nota.*?([\d\.]+,\d{2})\s*([CD])",
            'irrf_1': r"IRRF Day Trade.*?([\d\.]+,\d{2})",
            'taxas_b3': r"Taxas BM&F \(emol\+fgar\).*?([\d\.]+,\d{2})",
            'taxa_reg': r"Taxa registro BM&F.*?([\d\.]+,\d{2})"
        }

        def processar(label):
            match = re.search(padroes[label], texto_completo, re.IGNORECASE | re.DOTALL)
            if not match: return 0.0
            val = float(match.group(1).replace('.', '').replace(',', '.'))
            if label == 'liquido' and match.group(2).upper() == 'D': val = -val
            return val

        return {
            'bruto': processar('bruto'),
            'liquido': processar('liquido'),
            'irrf_1': processar('irrf_1'),
            'taxas': processar('taxas_b3') + processar('taxa_reg')
        }
    except Exception:
        return None

