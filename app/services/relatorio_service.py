"""
Serviço para geração do Relatório de Gestão (Excel) com filtro por mês/ano.
REGRAS APLICADAS:
- Clientes isentos são EXCLUÍDOS de todos os cálculos (totais, médias, repasses).
- Clientes sem nenhuma nota no período não entram nos cálculos agregados, mas aparecem em uma seção separada "Clientes sem movimentação".
- Dias operados: removido indicador global.
- Todos os cálculos de valores financeiros usam "liquido_pregao" (resultado do pregão após custos, antes do IR 19%).
- O ROI Global é calculado com base no campo "bruto" (mesma lógica do dashboard admin):
    ROI cliente = (média diária bruta / capital) * 100
    ROI Global = média dos ROIs individuais (clientes com capital > 0 e dias positivos).
- Colunas por cliente: Nome, CPF, Conta MT5, Modelo, Capital (R$), Média Diária (R$), Média Semanal (R$), Total Mensal (R$), Repasse 30% (R$).
"""

from datetime import datetime
import calendar
import pytz
from app import db
from app.models import User, Fatura, FaturaDiaria
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import tempfile
import os

tz_br = pytz.timezone('America/Sao_Paulo')

# Cores para linhas de clientes
AZUL_CLARO = PatternFill(start_color="D9EAF7", end_color="D9EAF7", fill_type="solid")
VERDE_CLARO = PatternFill(start_color="D5F5E3", end_color="D5F5E3", fill_type="solid")
BRANCO = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")


def gerar_relatorio_gestao(mes, ano):
    """
    Gera relatório filtrado pelo mês/ano informado.
    Retorna caminho do arquivo Excel temporário.
    """
    # Determinar primeiro e último dia do mês
    primeiro_dia = datetime(ano, mes, 1).date()
    ultimo_dia = datetime(ano, mes, calendar.monthrange(ano, mes)[1]).date()

    wb = Workbook()
    ws = wb.active
    ws.title = f"Gestao_{mes}_{ano}"

    # Estilos
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    subheader_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    center_align = Alignment(horizontal='center', vertical='center')
    left_align = Alignment(horizontal='left', vertical='center')
    right_align = Alignment(horizontal='right', vertical='center')
    currency_format = '"R$" #,##0.00'
    percent_format = '0.00"%"'

    # ==================== 1. TOTAIS GERAIS ====================
    ws.merge_cells('A1:H1')
    ws['A1'] = f'RELATÓRIO DE GESTÃO - {mes}/{ano}'
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = center_align
    ws['A1'].fill = header_fill
    ws['A1'].font = header_font

    # Buscar clientes ativos (role='cliente', status_acesso='ativo', NÃO isentos)
    clientes_ativos = User.query.filter(
        User.role == 'cliente',
        User.status_acesso == 'ativo',
        User.is_isento == False  # EXCLUI ISENTOS
    ).all()
    clientes_ativos_qtd = len(clientes_ativos)

    # Inicializar acumuladores globais
    total_capital = 0.0
    soma_liquido_positivo_total = 0.0   # soma de liquido_pregao de dias positivos
    total_dias_operados = 0             # total de dias com nota (apenas dias positivos)

    # Repasses
    repasse_todos_clientes_total = 0.0      # 30% sobre soma_liquido_positivo_total
    repasse_comissionados_total = 0.0       # 30% sobre soma de liquido_pregao de comissionados

    # Cálculo do ROI Global (mesma lógica do dashboard admin)
    rois_clientes = []   # armazenar ROI de cada cliente (média diária bruta / capital * 100)

    # Dados por cliente (ativos e não isentos)
    dados_clientes = []
    clientes_sem_notas = []  # para clientes ativos não isentos sem nenhuma nota no mês

    for cliente in clientes_ativos:
        # Filtrar dias do mês para este cliente
        # Para valores financeiros: usa liquido_pregao > 0
        # Para ROI: usa bruto > 0
        dias_financeiros = FaturaDiaria.query.join(Fatura).filter(
            Fatura.user_id == cliente.id,
            FaturaDiaria.data_pregao >= primeiro_dia,
            FaturaDiaria.data_pregao <= ultimo_dia,
            FaturaDiaria.status == 'relatorio_enviado',
            FaturaDiaria.liquido_pregao > 0
        ).all()

        dias_roi = FaturaDiaria.query.join(Fatura).filter(
            Fatura.user_id == cliente.id,
            FaturaDiaria.data_pregao >= primeiro_dia,
            FaturaDiaria.data_pregao <= ultimo_dia,
            FaturaDiaria.status == 'relatorio_enviado',
            FaturaDiaria.bruto > 0
        ).all()

        # Capital acumula sempre (mesmo se não tiver notas)
        capital_cliente = cliente.capital_alocado or 0.0
        total_capital += capital_cliente

        if not dias_financeiros:
            # Cliente sem notas positivas no mês
            clientes_sem_notas.append({
                'nome': cliente.nome,
                'cpf': cliente.cpf,
                'conta_mt5': cliente.conta_mt5 or '',
                'modelo': cliente.modelo_negocio,
                'capital': capital_cliente
            })
            # Ainda assim, se tiver dias_roi (bruto > 0), pode contribuir para ROI? 
            # Para consistência com dashboard, só considera cliente se tiver pelo menos um dia com bruto > 0 e capital > 0
            if dias_roi and capital_cliente > 0:
                qtd_dias_roi = len(dias_roi)
                soma_bruto = sum(d.bruto for d in dias_roi)
                media_bruta = soma_bruto / qtd_dias_roi
                roi_cliente = (media_bruta / capital_cliente) * 100
                rois_clientes.append(roi_cliente)
            continue

        # Cálculos financeiros para este cliente (base liquido_pregao)
        qtd_dias_fin = len(dias_financeiros)
        soma_liquido = sum(d.liquido_pregao for d in dias_financeiros)

        media_diaria = soma_liquido / qtd_dias_fin if qtd_dias_fin > 0 else 0.0
        media_semanal = media_diaria * 5
        total_mensal = soma_liquido
        repasse_cliente = soma_liquido * 0.30

        # Acumular totais globais (financeiros)
        total_dias_operados += qtd_dias_fin
        soma_liquido_positivo_total += soma_liquido
        repasse_todos_clientes_total += repasse_cliente
        if cliente.modelo_negocio == 'comissao':
            repasse_comissionados_total += repasse_cliente

        # Cálculo do ROI para este cliente (base bruto)
        if dias_roi and capital_cliente > 0:
            qtd_dias_roi = len(dias_roi)
            soma_bruto = sum(d.bruto for d in dias_roi)
            media_bruta = soma_bruto / qtd_dias_roi
            roi_cliente = (media_bruta / capital_cliente) * 100
            rois_clientes.append(roi_cliente)

        dados_clientes.append({
            'nome': cliente.nome,
            'cpf': cliente.cpf,
            'conta_mt5': cliente.conta_mt5 or '',
            'modelo': cliente.modelo_negocio,
            'capital': capital_cliente,
            'media_diaria': media_diaria,
            'media_semanal': media_semanal,
            'total_mensal': total_mensal,
            'repasse': repasse_cliente
        })

    # Calcular ROI Global (média dos ROIs individuais)
    roi_global = sum(rois_clientes) / len(rois_clientes) if rois_clientes else 0.0

    # Calcular médias globais (financeiras)
    media_diaria_global = soma_liquido_positivo_total / total_dias_operados if total_dias_operados > 0 else 0.0
    media_semanal_global = media_diaria_global * 5
    total_mensal_global = soma_liquido_positivo_total

    # Escrever totais gerais
    linha = 3
    ws.cell(row=linha, column=1, value='INDICADOR').fill = subheader_fill
    ws.cell(row=linha, column=2, value='VALOR').fill = subheader_fill
    linha += 1
    ws.cell(row=linha, column=1, value='Clientes Ativos (não isentos)')
    ws.cell(row=linha, column=2, value=clientes_ativos_qtd)
    linha += 1
    ws.cell(row=linha, column=1, value='Capital Total Alocado (R$)')
    ws.cell(row=linha, column=2, value=total_capital).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='Média Diária Global (R$)')
    ws.cell(row=linha, column=2, value=media_diaria_global).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='Média Semanal Global (R$)')
    ws.cell(row=linha, column=2, value=media_semanal_global).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='Total Mensal Líquido (R$)')
    ws.cell(row=linha, column=2, value=total_mensal_global).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='REPASSE 30% (Todos clientes) (R$)')
    ws.cell(row=linha, column=2, value=repasse_todos_clientes_total).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='REPASSE 30% (Comissionados) (R$)')
    ws.cell(row=linha, column=2, value=repasse_comissionados_total).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='ROI Médio Global (%)')
    ws.cell(row=linha, column=2, value=round(roi_global, 2)).number_format = percent_format

    # Aplicar bordas e alinhamento nos totais
    for row in range(3, linha+1):
        for col in [1,2]:
            cell = ws.cell(row=row, column=col)
            cell.border = thin_border
            if col == 2:
                cell.alignment = right_align
            else:
                cell.alignment = left_align

    # ==================== 2. DETALHAMENTO POR CLIENTE ATIVO (COM NOTAS) ====================
    if dados_clientes:
        linha += 2
        ws.cell(row=linha, column=1, value='DETALHAMENTO POR CLIENTE ATIVO').font = Font(bold=True, size=12)
        linha += 1

        headers = [
            'Nome', 'CPF', 'Conta MT5', 'Modelo', 'Capital (R$)',
            'Média Diária (R$)', 'Média Semanal (R$)', 'Total Mensal (R$)', 'Repasse 30% (R$)'
        ]
        for idx, header in enumerate(headers):
            cell = ws.cell(row=linha, column=1+idx, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.border = thin_border
            cell.alignment = center_align

        linha += 1
        for cli in dados_clientes:
            # Definir cor de fundo conforme modelo
            if cli['modelo'] == 'comissao':
                bg_fill = AZUL_CLARO
            else:  # compra
                bg_fill = VERDE_CLARO

            ws.cell(row=linha, column=1, value=cli['nome']).border = thin_border
            ws.cell(row=linha, column=2, value=cli['cpf']).border = thin_border
            ws.cell(row=linha, column=3, value=cli['conta_mt5']).border = thin_border
            modelo_str = 'Comissão' if cli['modelo'] == 'comissao' else 'Compra'
            ws.cell(row=linha, column=4, value=modelo_str).border = thin_border

            cell_capital = ws.cell(row=linha, column=5, value=round(cli['capital'], 2))
            cell_capital.number_format = currency_format
            cell_capital.border = thin_border
            cell_capital.fill = bg_fill

            cell_media_diaria = ws.cell(row=linha, column=6, value=round(cli['media_diaria'], 2))
            cell_media_diaria.number_format = currency_format
            cell_media_diaria.border = thin_border
            cell_media_diaria.fill = bg_fill

            cell_media_semanal = ws.cell(row=linha, column=7, value=round(cli['media_semanal'], 2))
            cell_media_semanal.number_format = currency_format
            cell_media_semanal.border = thin_border
            cell_media_semanal.fill = bg_fill

            cell_total = ws.cell(row=linha, column=8, value=round(cli['total_mensal'], 2))
            cell_total.number_format = currency_format
            cell_total.border = thin_border
            cell_total.fill = bg_fill

            cell_repasse = ws.cell(row=linha, column=9, value=round(cli['repasse'], 2))
            cell_repasse.number_format = currency_format
            cell_repasse.border = thin_border
            cell_repasse.fill = bg_fill

            # Alinhamento
            for col in range(1, 10):
                cell = ws.cell(row=linha, column=col)
                if col >= 5:
                    cell.alignment = right_align
                else:
                    cell.alignment = left_align
                cell.fill = bg_fill

            linha += 1

    # ==================== 3. CLIENTES ATIVOS SEM MOVIMENTAÇÃO NO MÊS ====================
    if clientes_sem_notas:
        linha += 2
        ws.cell(row=linha, column=1, value='CLIENTES ATIVOS SEM NOTAS NO PERÍODO').font = Font(bold=True, size=12)
        linha += 1

        headers_sem = ['Nome', 'CPF', 'Conta MT5', 'Modelo', 'Capital (R$)']
        for idx, header in enumerate(headers_sem):
            cell = ws.cell(row=linha, column=1+idx, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.border = thin_border
            cell.alignment = center_align

        linha += 1
        for cli in clientes_sem_notas:
            modelo_str = 'Comissão' if cli['modelo'] == 'comissao' else 'Compra'
            ws.cell(row=linha, column=1, value=cli['nome']).border = thin_border
            ws.cell(row=linha, column=2, value=cli['cpf']).border = thin_border
            ws.cell(row=linha, column=3, value=cli['conta_mt5']).border = thin_border
            ws.cell(row=linha, column=4, value=modelo_str).border = thin_border
            cell_capital = ws.cell(row=linha, column=5, value=round(cli['capital'], 2))
            cell_capital.number_format = currency_format
            cell_capital.border = thin_border

            for col in range(1, 6):
                cell = ws.cell(row=linha, column=col)
                if col == 5:
                    cell.alignment = right_align
                else:
                    cell.alignment = left_align
            linha += 1

    # Ajustar larguras (sem a coluna de ROI)
    column_widths = [30, 15, 12, 12, 15, 15, 15, 15, 18]
    for i, width in enumerate(column_widths, start=1):
        col_letter = chr(64 + i) if i <= 26 else 'A' + chr(64 + (i-26))
        ws.column_dimensions[col_letter].width = width

    fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
    os.close(fd)
    wb.save(temp_path)
    return temp_path
