import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

def gerar_relatorio_pendencias(dados, caminho_saida):
    """
    Gera um arquivo Excel formatado com os clientes e suas respectivas
    datas pendentes, mesclando o nome na vertical como um relatório limpo.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "NOTAS PENDENTES"

    # Estilos exatos do modelo (Cores, Fontes e Bordas)
    azul_fill = PatternFill(start_color="8EA9DB", end_color="8EA9DB", fill_type="solid")
    fonte_branca_bold = Font(color="FFFFFF", bold=True, size=12)
    fonte_preta = Font(color="000000", size=11)
    alinhamento_centro = Alignment(horizontal="center", vertical="center")
    
    borda_fina = Border(
        left=Side(style='thin', color="000000"), 
        right=Side(style='thin', color="000000"),
        top=Side(style='thin', color="000000"), 
        bottom=Side(style='thin', color="000000")
    )

    # 1. Cabeçalho Principal (A1:B1)
    ws.merge_cells('A1:B1')
    ws['A1'] = "NOTAS PENDENTES DE LANÇAMENTO"
    ws['A1'].fill = azul_fill
    ws['A1'].font = fonte_branca_bold
    ws['A1'].alignment = alinhamento_centro
    ws['A1'].border = borda_fina
    ws['B1'].border = borda_fina

    # 2. Subcabeçalho (A2 e B2)
    ws['A2'] = "NOME"
    ws['A2'].fill = azul_fill
    ws['A2'].font = fonte_branca_bold
    ws['A2'].alignment = alinhamento_centro
    ws['A2'].border = borda_fina

    ws['B2'] = "DATA"
    ws['B2'].fill = azul_fill
    ws['B2'].font = fonte_branca_bold
    ws['B2'].alignment = alinhamento_centro
    ws['B2'].border = borda_fina

    # 3. Largura das colunas ajustadas para respirar
    ws.column_dimensions['A'].width = 35
    ws.column_dimensions['B'].width = 20

    # 4. Inserção Dinâmica dos Dados
    linha_atual = 3

    for cliente in dados:
        nome = cliente['nome']
        datas = cliente['datas']
        
        linha_inicio = linha_atual
        
        # Preenche a coluna de datas primeiro
        for data in datas:
            celula_data = ws.cell(row=linha_atual, column=2, value=data)
            celula_data.alignment = alinhamento_centro
            celula_data.font = fonte_preta
            celula_data.border = borda_fina
            linha_atual += 1
            
        linha_fim = linha_atual - 1
        
        # Mescla a coluna do NOME na vertical se houver mais de 1 data pendente
        if linha_inicio < linha_fim:
            ws.merge_cells(start_row=linha_inicio, start_column=1, end_row=linha_fim, end_column=1)
        
        # Escreve o nome centralizado na célula mesclada
        celula_nome = ws.cell(row=linha_inicio, column=1, value=nome)
        celula_nome.alignment = alinhamento_centro
        celula_nome.font = fonte_preta
        
        # Pinta a borda de toda a "caixa" do nome
        for r in range(linha_inicio, linha_fim + 1):
            ws.cell(row=r, column=1).border = borda_fina

    wb.save(caminho_saida)
    return True