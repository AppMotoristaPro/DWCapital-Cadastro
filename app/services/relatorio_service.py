"""
Serviço para geração do Relatório de Gestão (Excel) com filtro por mês/ano.
Regras implementadas:
- Média diária: soma total de ganhos/perdas dividido por dias operados (notas enviadas).
- Média semanal: média diária * 5.
- Total mensal: soma líquida do mês (ganhos - perdas).
- Repasse real (dias de ganho): soma do campo repasse (já 30% sobre dias positivos) apenas para comissionados não isentos.
- Repasse real (saldo mensal): 30% do saldo líquido do mês (se positivo) para comissionados não isentos.
- Repasse simulado (dias de ganho): 30% da soma do líquido dos dias positivos, para todos não isentos.
- Repasse simulado (saldo mensal): 30% do saldo líquido do mês (se positivo) para todos não isentos.
- Totais globais somam valores de todos os clientes ativos.
"""

from datetime import datetime, timedelta
import calendar
import pytz
from app import db
from app.models import User, Fatura, FaturaDiaria
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import tempfile
import os

tz_br = pytz.timezone('America/Sao_Paulo')


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
    ws.title = f"Gestão {mes}/{ano}"

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

    # ==================== 1. TOTAIS GERAIS ====================
    ws.merge_cells('A1:H1')
    ws['A1'] = f'RELATÓRIO DE GESTÃO - {mes}/{ano}'
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = center_align
    ws['A1'].fill = header_fill
    ws['A1'].font = header_font

    # Buscar clientes ativos
    clientes_ativos = User.query.filter_by(role='cliente', status_acesso='ativo').all()
    clientes_ativos_qtd = len(clientes_ativos)

    # Inicializar acumuladores
    total_capital = 0.0
    total_dias_operados = 0
    soma_liquido_total = 0.0
    soma_liquido_positivo_total = 0.0   # para repasse simulado (dias de ganho)
    saldo_mensal_total = 0.0            # soma líquida (ganhos - perdas)
    repasse_real_dias_total = 0.0       # soma do repasse (já é 30% sobre dias positivos) - comissionados não isentos
    repasse_real_saldo_total = 0.0      # 30% do saldo mensal (se positivo) - comissionados não isentos
    repasse_simulado_dias_total = 0.0   # 30% da soma de líquido de dias positivos - todos não isentos
    repasse_simulado_saldo_total = 0.0  # 30% do saldo mensal (se positivo) - todos não isentos

    # Dados por cliente
    dados_clientes = []

    for cliente in clientes_ativos:
        # Filtrar dias do mês para este cliente
        dias = FaturaDiaria.query.join(Fatura).filter(
            Fatura.user_id == cliente.id,
            FaturaDiaria.data_pregao >= primeiro_dia,
            FaturaDiaria.data_pregao <= ultimo_dia,
            FaturaDiaria.status == 'relatorio_enviado'
        ).all()

        if not dias:
            # Cliente sem nenhuma nota no mês – ainda assim pode ter capital alocado
            total_capital += cliente.capital_alocado or 0.0
            dados_clientes.append({
                'nome': cliente.nome,
                'cpf': cliente.cpf,
                'conta_mt5': cliente.conta_mt5 or '',
                'modelo': cliente.modelo_negocio,
                'is_isento': cliente.is_isento,
                'capital': cliente.capital_alocado or 0.0,
                'dias_operados': 0,
                'media_diaria': 0.0,
                'media_semanal': 0.0,
                'total_mensal': 0.0,
                'repasse_real_dias': 0.0,
                'repasse_real_saldo': 0.0,
                'repasse_simulado_dias': 0.0,
                'repasse_simulado_saldo': 0.0
            })
            continue

        # Cálculos para este cliente
        qtd_dias = len(dias)
        soma_liquido = sum(d.liquido for d in dias)
        soma_liquido_positivo = sum(d.liquido for d in dias if d.liquido > 0)
        saldo_mensal = soma_liquido  # já inclui ganhos e perdas
        media_diaria = soma_liquido / qtd_dias if qtd_dias > 0 else 0.0
        media_semanal = media_diaria * 5

        # Repasse real (apenas comissionados não isentos) – sobre dias de ganho
        repasse_real_dias = 0.0
        repasse_real_saldo = 0.0
        if cliente.modelo_negocio == 'comissao' and not cliente.is_isento:
            # Soma do campo repasse (já calculado como 30% do líquido dia >0)
            repasse_real_dias = sum(d.repasse for d in dias)
            # Sobre o saldo mensal (se positivo)
            if saldo_mensal > 0:
                repasse_real_saldo = saldo_mensal * 0.30

        # Repasse simulado (todos não isentos) – 30% sobre líquido de dias positivos e sobre saldo mensal
        repasse_simulado_dias = 0.0
        repasse_simulado_saldo = 0.0
        if not cliente.is_isento:
            repasse_simulado_dias = soma_liquido_positivo * 0.30
            if saldo_mensal > 0:
                repasse_simulado_saldo = saldo_mensal * 0.30

        # Acumular totais globais
        total_capital += cliente.capital_alocado or 0.0
        total_dias_operados += qtd_dias
        soma_liquido_total += soma_liquido
        soma_liquido_positivo_total += soma_liquido_positivo
        saldo_mensal_total += saldo_mensal
        repasse_real_dias_total += repasse_real_dias
        repasse_real_saldo_total += repasse_real_saldo
        repasse_simulado_dias_total += repasse_simulado_dias
        repasse_simulado_saldo_total += repasse_simulado_saldo

        dados_clientes.append({
            'nome': cliente.nome,
            'cpf': cliente.cpf,
            'conta_mt5': cliente.conta_mt5 or '',
            'modelo': 'Comissão' if cliente.modelo_negocio == 'comissao' else 'Compra',
            'is_isento': cliente.is_isento,
            'capital': cliente.capital_alocado or 0.0,
            'dias_operados': qtd_dias,
            'media_diaria': media_diaria,
            'media_semanal': media_semanal,
            'total_mensal': soma_liquido,
            'repasse_real_dias': repasse_real_dias,
            'repasse_real_saldo': repasse_real_saldo,
            'repasse_simulado_dias': repasse_simulado_dias,
            'repasse_simulado_saldo': repasse_simulado_saldo
        })

    # Calcular médias globais
    media_diaria_global = soma_liquido_total / total_dias_operados if total_dias_operados > 0 else 0.0
    media_semanal_global = media_diaria_global * 5
    total_mensal_global = soma_liquido_total  # já é a soma líquida

    # Escrever totais gerais
    linha = 3
    ws.cell(row=linha, column=1, value='INDICADOR').fill = subheader_fill
    ws.cell(row=linha, column=2, value='VALOR').fill = subheader_fill
    linha += 1
    ws.cell(row=linha, column=1, value='Clientes Ativos')
    ws.cell(row=linha, column=2, value=clientes_ativos_qtd)
    linha += 1
    ws.cell(row=linha, column=1, value='Capital Total Alocado (R$)')
    ws.cell(row=linha, column=2, value=total_capital).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='Dias Operados (total)')
    ws.cell(row=linha, column=2, value=total_dias_operados)
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
    ws.cell(row=linha, column=1, value='Repasse Real - Dias de Ganho (R$)')
    ws.cell(row=linha, column=2, value=repasse_real_dias_total).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='Repasse Real - Saldo Mensal (30% sobre saldo positivo) (R$)')
    ws.cell(row=linha, column=2, value=repasse_real_saldo_total).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='Repasse Simulado - Dias de Ganho (R$)')
    ws.cell(row=linha, column=2, value=repasse_simulado_dias_total).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='Repasse Simulado - Saldo Mensal (30% sobre saldo positivo) (R$)')
    ws.cell(row=linha, column=2, value=repasse_simulado_saldo_total).number_format = currency_format

    # Aplicar bordas e alinhamento nos totais
    for row in range(3, linha+1):
        for col in [1,2]:
            cell = ws.cell(row=row, column=col)
            cell.border = thin_border
            if col == 2:
                cell.alignment = right_align
            else:
                cell.alignment = left_align

    # ==================== 2. DETALHAMENTO POR CLIENTE ====================
    linha += 2
    ws.cell(row=linha, column=1, value='DETALHAMENTO POR CLIENTE ATIVO').font = Font(bold=True, size=12)
    linha += 1

    headers = [
        'Nome', 'CPF', 'Conta MT5', 'Modelo', 'Isento', 'Capital (R$)',
        'Dias Operados', 'Média Diária (R$)', 'Média Semanal (R$)', 'Total Mensal (R$)',
        'Repasse Real (dias ganho) (R$)', 'Repasse Real (saldo mensal) (R$)',
        'Repasse Simulado (dias ganho) (R$)', 'Repasse Simulado (saldo mensal) (R$)'
    ]
    for idx, header in enumerate(headers):
        cell = ws.cell(row=linha, column=1+idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin_border
        cell.alignment = center_align

    linha += 1
    for cli in dados_clientes:
        # Isento -> Sim/Não
        isento = 'Sim' if cli.get('is_isento') else 'Não'
        ws.cell(row=linha, column=1, value=cli['nome']).border = thin_border
        ws.cell(row=linha, column=2, value=cli['cpf']).border = thin_border
        ws.cell(row=linha, column=3, value=cli['conta_mt5']).border = thin_border
        ws.cell(row=linha, column=4, value=cli['modelo']).border = thin_border
        ws.cell(row=linha, column=5, value=isento).border = thin_border

        # Valores monetários com formatação
        cell_capital = ws.cell(row=linha, column=6, value=round(cli['capital'], 2))
        cell_capital.number_format = currency_format
        cell_capital.border = thin_border

        ws.cell(row=linha, column=7, value=cli['dias_operados']).border = thin_border

        cell_media_diaria = ws.cell(row=linha, column=8, value=round(cli['media_diaria'], 2))
        cell_media_diaria.number_format = currency_format
        cell_media_diaria.border = thin_border

        cell_media_semanal = ws.cell(row=linha, column=9, value=round(cli['media_semanal'], 2))
        cell_media_semanal.number_format = currency_format
        cell_media_semanal.border = thin_border

        cell_total_mensal = ws.cell(row=linha, column=10, value=round(cli['total_mensal'], 2))
        cell_total_mensal.number_format = currency_format
        cell_total_mensal.border = thin_border

        cell_rep_real_dias = ws.cell(row=linha, column=11, value=round(cli['repasse_real_dias'], 2))
        cell_rep_real_dias.number_format = currency_format
        cell_rep_real_dias.border = thin_border

        cell_rep_real_saldo = ws.cell(row=linha, column=12, value=round(cli['repasse_real_saldo'], 2))
        cell_rep_real_saldo.number_format = currency_format
        cell_rep_real_saldo.border = thin_border

        cell_rep_sim_dias = ws.cell(row=linha, column=13, value=round(cli['repasse_simulado_dias'], 2))
        cell_rep_sim_dias.number_format = currency_format
        cell_rep_sim_dias.border = thin_border

        cell_rep_sim_saldo = ws.cell(row=linha, column=14, value=round(cli['repasse_simulado_saldo'], 2))
        cell_rep_sim_saldo.number_format = currency_format
        cell_rep_sim_saldo.border = thin_border

        # Alinhamento
        for col in range(1, 15):
            cell = ws.cell(row=linha, column=col)
            if col >= 6:  # valores numéricos
                cell.alignment = right_align
            else:
                cell.alignment = left_align

        linha += 1

    # Ajustar larguras
    column_widths = [25, 15, 12, 12, 8, 15, 12, 15, 15, 15, 18, 18, 18, 18]
    for i, width in enumerate(column_widths, start=1):
        col_letter = chr(64 + i) if i <= 26 else 'A' + chr(64 + (i-26))
        ws.column_dimensions[col_letter].width = width

    fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
    os.close(fd)
    wb.save(temp_path)
    return temp_path
