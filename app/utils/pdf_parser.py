import re
from pypdf import PdfReader

def extrair_dados_nota_corretagem(caminho_arquivo):
    try:
        print(f"--- INICIANDO LEITURA DO PDF: {caminho_arquivo} ---")
        leitor = PdfReader(caminho_arquivo)
        texto_completo = ""
        
        for i, pagina in enumerate(leitor.pages):
            texto_pag = pagina.extract_text() or ""
            texto_completo += texto_pag + "\n"
            print(f"DEBUG: Texto da Página {i+1} extraído (Tamanho: {len(texto_pag)} caracteres)")

        # LOG PARA O RENDER: Exibe o texto bruto para depuração
        print("--- CONTEÚDO BRUTO DO PDF ---")
        print(texto_completo)
        print("--- FIM DO CONTEÚDO BRUTO ---")

        def buscar_valor(label, regex, texto):
            # re.DOTALL permite que o '.' encontre quebras de linha
            match = re.search(regex, texto, re.IGNORECASE | re.DOTALL)
            if match:
                valor_limpo = match.group(1).replace('.', '').replace(',', '.')
                valor = float(valor_limpo)
                
                # [span_3](start_span)Para o líquido, verifica se é Crédito (C) ou Débito (D)[span_3](end_span)
                if label == 'liquido' and match.group(2).upper() == 'D':
                    valor = -valor
                
                print(f"LOG: {label} encontrado -> {valor}")
                return valor
            print(f"LOG: {label} não encontrado no texto.")
            return 0.0

        # [span_4](start_span)[span_5](start_span)Regex flexíveis baseadas na estrutura da Genial[span_4](end_span)[span_5](end_span)
        # [span_6](start_span)Captura o valor e o indicador C/D[span_6](end_span)
        dados = {
            'bruto': buscar_valor('bruto', r"Ajuste day trade.*?([\d\.,]+\d{2})", texto_completo),
            'liquido': buscar_valor('liquido', r"Total l[ií]quido da nota.*?([\d\.,]+\d{2})\s*([CD])", texto_completo),
            'irrf_1': buscar_valor('irrf', r"IRRF Day Trade.*?([\d\.,]+\d{2})", texto_completo),
            't_bmf': buscar_valor('t_bmf', r"Taxas BM&F \(emol\+fgar\).*?([\d\.,]+\d{2})", texto_completo),
            't_reg': buscar_valor('t_reg', r"Taxa registro BM&F.*?([\d\.,]+\d{2})", texto_completo)
        }
        
        dados['taxas_b3'] = dados['t_bmf'] + dados['t_reg']
        return dados

    except Exception as e:
        print(f"ERRO CRÍTICO NO PARSER: {str(e)}")
        return None

