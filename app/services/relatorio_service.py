"""
Serviço para geração do Relatório de Gestão (Excel) com formatação de moeda brasileira (R$).
"""

from datetime import datetime, timedelta
import pytz
from app import db
from app.models import User, Fatura, FaturaDiaria
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
import tempfile
import os

tz_br = pytz.timezone('America/Sao_Paulo')


def gerar_relatorio_gestao():
    """
    Gera um arquivo Excel com o relatório de gestão.
    Retorna o caminho do arquivo temporário.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Gestão Geral"

    # Estilos
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    subheader_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    subheader_font = Font(bold=True, size=10)
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    center_align = Alignment(horizontal='center', vertical='center')
    left_align = Alignment(horizontal='left', vertical='center')
    right_align = Alignment(horizontal='right', vertical='center')

    # Formato de moeda brasileira
    currency_format = numbers.FORMAT_CURRENCY_BRL_SIMPLE  # 'R$ #,##0.00'
    # Ou para garantir: '"R$" #,##0.00'

    # ==================== 1. TOTAIS GERAIS ====================
    ws.merge_cells('A1:E1')
    ws['A1'] = 'RELATÓRIO DE GESTÃO - DW CAPITAL'
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = center_align
    ws['A1'].fill = header_fill
    ws['A1'].font = header_font

    # Consultas
    clientes_ativos = User.query.filter_by(role='cliente', status_acesso='ativo').count()
    clientes_inativos = User.query.filter_by(role='cliente', status_acesso='inativo').count()
    capital_total = db.session.query(db.func.sum(User.capital_alocado)).filter(
        User.role == 'cliente', User.status_acesso == 'ativo'
    ).scalar() or 0.0

    # Médias de ganhos
    dias_operados = db.session.query(FaturaDiaria.liquido).join(Fatura).join(User).filter(
        User.role == 'cliente',
        User.status_acesso == 'ativo',
        FaturaDiaria.status == 'relatorio_enviado'
    ).all()
    if dias_operados:
        soma_liquido = sum(d.liquido for d in dias_operados if d.liquido)
        qtd_dias = len(dias_operados)
        media_diaria = soma_liquido / qtd_dias if qtd_dias > 0 else 0.0
        media_semanal_global = media_diaria * 5
        media_mensal_global = media_diaria * 22
    else:
        media_semanal_global = 0.0
        media_mensal_global = 0.0

    # Repasse real (apenas comissionados não isentos)
    repasse_real = db.session.query(db.func.sum(Fatura.repasse)).join(User).filter(
        User.modelo_negocio == 'comissao',
        db.or_(User.is_isento == False, User.is_isento.is_(None))
    ).scalar() or 0.0

    # Repasse simulado (30% sobre o liquido de todos, exceto isentos)
    liquido_total_nao_isentos = db.session.query(db.func.sum(FaturaDiaria.liquido)).join(Fatura).join(User).filter(
        User.is_isento == False,
        FaturaDiaria.status == 'relatorio_enviado'
    ).scalar() or 0.0
    repasse_simulado = liquido_total_nao_isentos * 0.30

    # Escrever totais gerais
    linha = 3
    ws.cell(row=linha, column=1, value='INDICADOR').fill = subheader_fill
    ws.cell(row=linha, column=2, value='VALOR').fill = subheader_fill
    linha += 1
    ws.cell(row=linha, column=1, value='Clientes Ativos')
    ws.cell(row=linha, column=2, value=clientes_ativos)
    linha += 1
    ws.cell(row=linha, column=1, value='Clientes Inativos')
    ws.cell(row=linha, column=2, value=clientes_inativos)
    linha += 1
    ws.cell(row=linha, column=1, value='Capital Total Alocado (R$)')
    ws.cell(row=linha, column=2, value=capital_total)
    ws.cell(row=linha, column=2).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='Média de Ganhos Semanais (Global - R$)')
    ws.cell(row=linha, column=2, value=round(media_semanal_global, 2))
    ws.cell(row=linha, column=2).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='Média de Ganhos Mensais (Global - R$)')
    ws.cell(row=linha, column=2, value=round(media_mensal_global, 2))
    ws.cell(row=linha, column=2).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='Repasse Real DW (R$)')
    ws.cell(row=linha, column=2, value=round(repasse_real, 2))
    ws.cell(row=linha, column=2).number_format = currency_format
    linha += 1
    ws.cell(row=linha, column=1, value='Repasse Simulado DW (30% sobre todos não isentos - R$)')
    ws.cell(row=linha, column=2, value=round(repasse_simulado, 2))
    ws.cell(row=linha, column=2).number_format = currency_format

    # Aplicar bordas e alinhamento nas células de totais
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

    # Cabeçalhos da tabela de clientes
    headers = [
        'Nome', 'CPF', 'Conta MT5', 'Modelo', 'Capital Alocado (R$)',
        'Ganho Médio Semanal (R$)', 'Ganho Médio Mensal (R$)',
        'Repasse Real (R$)', 'Repasse Simulado (R$)'
    ]
    col_inicial = 1
    for idx, header in enumerate(headers):
        cell = ws.cell(row=linha, column=col_inicial + idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin_border
        cell.alignment = center_align

    linha += 1

    # Buscar clientes ativos
    clientes = User.query.filter_by(role='cliente', status_acesso='ativo').order_by(User.nome).all()

    for cliente in clientes:
        # Calcular médias individuais
        dias_cliente = FaturaDiaria.query.join(Fatura).filter(
            Fatura.user_id == cliente.id,
            FaturaDiaria.status == 'relatorio_enviado'
        ).all()
        if dias_cliente:
            soma_liquido_cliente = sum(d.liquido for d in dias_cliente if d.liquido)
            qtd_dias_cliente = len(dias_cliente)
            media_diaria_cliente = soma_liquido_cliente / qtd_dias_cliente if qtd_dias_cliente > 0 else 0.0
            ganho_semanal = media_diaria_cliente * 5
            ganho_mensal = media_diaria_cliente * 22
        else:
            ganho_semanal = 0.0
            ganho_mensal = 0.0

        # Repasse real (apenas comissão não isento)
        if cliente.modelo_negocio == 'comissao' and not cliente.is_isento:
            repasse_real_cliente = db.session.query(db.func.sum(Fatura.repasse)).filter(
                Fatura.user_id == cliente.id
            ).scalar() or 0.0
        else:
            repasse_real_cliente = 0.0

        # Repasse simulado (30% do liquido total do cliente)
        liquido_total_cliente = db.session.query(db.func.sum(FaturaDiaria.liquido)).join(Fatura).filter(
            Fatura.user_id == cliente.id,
            FaturaDiaria.status == 'relatorio_enviado'
        ).scalar() or 0.0
        repasse_simulado_cliente = liquido_total_cliente * 0.30

        # Escrever linha
        ws.cell(row=linha, column=1, value=cliente.nome).border = thin_border
        ws.cell(row=linha, column=2, value=cliente.cpf).border = thin_border
        ws.cell(row=linha, column=3, value=cliente.conta_mt5 or '').border = thin_border
        modelo_str = 'Comissão' if cliente.modelo_negocio == 'comissao' else 'Compra'
        ws.cell(row=linha, column=4, value=modelo_str).border = thin_border

        # Valores monetários com formatação
        cell_capital = ws.cell(row=linha, column=5, value=round(cliente.capital_alocado or 0.0, 2))
        cell_capital.number_format = currency_format
        cell_capital.border = thin_border

        cell_semanal = ws.cell(row=linha, column=6, value=round(ganho_semanal, 2))
        cell_semanal.number_format = currency_format
        cell_semanal.border = thin_border

        cell_mensal = ws.cell(row=linha, column=7, value=round(ganho_mensal, 2))
        cell_mensal.number_format = currency_format
        cell_mensal.border = thin_border

        cell_repasse_real = ws.cell(row=linha, column=8, value=round(repasse_real_cliente, 2))
        cell_repasse_real.number_format = currency_format
        cell_repasse_real.border = thin_border

        cell_repasse_sim = ws.cell(row=linha, column=9, value=round(repasse_simulado_cliente, 2))
        cell_repasse_sim.number_format = currency_format
        cell_repasse_sim.border = thin_border

        # Alinhamento
        for col in range(1, 10):
            cell = ws.cell(row=linha, column=col)
            if col >= 5:  # valores numéricos
                cell.alignment = right_align
            else:
                cell.alignment = left_align

        linha += 1

    # Ajustar larguras das colunas
    column_widths = [30, 15, 12, 12, 18, 20, 20, 18, 18]
    for i, width in enumerate(column_widths, start=1):
        col_letter = chr(64 + i) if i <= 26 else 'A' + chr(64 + (i-26))  # suporte até 52
        ws.column_dimensions[col_letter].width = width

    # Salvar em arquivo temporário
    fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
    os.close(fd)
    wb.save(temp_path)
    return temp_path
