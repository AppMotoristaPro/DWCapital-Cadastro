import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from datetime import datetime, timedelta
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')

def gerar_relatorio_pendencias(usuarios_ativos, caminho_saida):
    """
    Exportador Híbrido: Calcula os dias que deveriam ter notas na vida do cliente (desde data de cadastro até ontem), 
    descarta os dias que já foram preenchidos no banco de dados e salva na planilha formatada.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "NOTAS PENDENTES"

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

    ws.merge_cells('A1:B1')
    ws['A1'] = "NOTAS PENDENTES DE LANÇAMENTO"
    ws['A1'].fill = azul_fill
    ws['A1'].font = fonte_branca_bold
    ws['A1'].alignment = alinhamento_centro
    ws['A1'].border = borda_fina
    ws['B1'].border = borda_fina

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

    ws.column_dimensions['A'].width = 35
    ws.column_dimensions['B'].width = 20

    hoje = datetime.now(tz_br).date()
    ontem = hoje - timedelta(days=1)
    
    dados = []
    
    for user in usuarios_ativos:
        data_cadastro = user.data_cadastro.date() if user.data_cadastro else datetime.min.date()
        
        # Cataloga os dias reais gravados no banco que o cliente já resolveu
        dias_resolvidos = set()
        for fatura in user.faturas:
            for dia in fatura.dias:
                if dia.status in ['relatorio_enviado', 'isento']:
                    dias_resolvidos.add(dia.data_pregao)
        
        # Gera o calendário virtual de obrigações dele
        dias_pendentes = []
        data_atual = data_cadastro
        
        # Condição crucial: Só cobra o que for menor ou igual a ONTEM
        while data_atual <= ontem:
            if data_atual.weekday() < 5: 
                if data_atual not in dias_resolvidos:
                    dias_pendentes.append(data_atual.strftime('%d/%m/%Y'))
            data_atual += timedelta(days=1)
            
        if dias_pendentes:
            dados.append({
                'nome': user.nome.upper(),
                'datas': dias_pendentes
            })

    if not dados:
        return False

    linha_atual = 3

    for cliente in dados:
        nome = cliente['nome']
        datas = cliente['datas']
        
        linha_inicio = linha_atual
        
        for data in datas:
            celula_data = ws.cell(row=linha_atual, column=2, value=data)
            celula_data.alignment = alinhamento_centro
            celula_data.font = fonte_preta
            celula_data.border = borda_fina
            linha_atual += 1
            
        linha_fim = linha_atual - 1
        
        if linha_inicio < linha_fim:
            ws.merge_cells(start_row=linha_inicio, start_column=1, end_row=linha_fim, end_column=1)
        
        celula_nome = ws.cell(row=linha_inicio, column=1, value=nome)
        celula_nome.alignment = alinhamento_centro
        celula_nome.font = fonte_preta
        
        for r in range(linha_inicio, linha_fim + 1):
            ws.cell(row=r, column=1).border = borda_fina

    wb.save(caminho_saida)
    return True

