from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload, contains_eager
from app import db
from app.models import Fatura, User
import pytz
from app.services.fatura_service import modelo_para_fatura

tz_br = pytz.timezone('America/Sao_Paulo')

def obter_dados_dashboard(filtro_dia, filtro_semana_dia, filtro_ano):
    """
    Processa toda a matemática do dashboard admin: filtros de data, 
    faturamento bruto/líquido, cálculo de ROI Diário Médio e agregação do gráfico.
    
    O ROI considera todos os clientes (comissionados, compra e isentos) que possuem
    pelo menos um dia com relatório enviado e valor bruto > 0.
    """
    faturas_base = Fatura.query.join(User).options(
        contains_eager(Fatura.cliente),
        joinedload(Fatura.dias)
    ).filter(
        Fatura.status.in_(['parcial', 'completo', 'pago', 'inadimplente'])
    )
    
    ano_atual = datetime.now(tz_br).year
    ano = ano_atual
    
    if filtro_dia:
        dt_dia = datetime.strptime(filtro_dia, '%Y-%m-%d').date()
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio <= dt_dia, Fatura.data_fim >= dt_dia).all()
        label_periodo = f"Dia {dt_dia.strftime('%d/%m/%Y')}"
        ano = dt_dia.year
        
    elif filtro_semana_dia:
        dt_ref = datetime.strptime(filtro_semana_dia, '%Y-%m-%d').date()
        dias_para_sexta = (dt_ref.weekday() - 4) % 7
        dt_inicio_sem = dt_ref - timedelta(days=dias_para_sexta)
        dt_fim_sem = dt_inicio_sem + timedelta(days=6)
        
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_sem, Fatura.data_inicio <= dt_fim_sem).all()
        label_periodo = f"Ciclo {dt_inicio_sem.strftime('%d/%m/%Y')} a {dt_fim_sem.strftime('%d/%m/%Y')}"
        ano = dt_inicio_sem.year
        
    elif filtro_ano:
        ano = int(filtro_ano)
        dt_inicio_ano = datetime(ano, 1, 1).date()
        dt_fim_ano = datetime(ano, 12, 31).date()
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_ano, Fatura.data_inicio <= dt_fim_ano).all()
        label_periodo = f"Ano {ano}"
        
    else:
        dt_inicio_ano = datetime(ano_atual, 1, 1).date()
        dt_fim_ano = datetime(ano_atual, 12, 31).date()
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_ano, Fatura.data_inicio <= dt_fim_ano).all()
        label_periodo = f"Ano {ano_atual}"
        
    faturamento_total = 0.0
    faturamento_bruto_total = 0.0
    dados_grafico_raw = {}
    rois_clientes = {}
    ranking_clientes = {} 

    for f in faturas_filtradas:
        # Determina modelo vigente com base na data de início da fatura
        modelo_cliente = modelo_para_fatura(f.cliente, f.data_inicio)
        is_isento_cliente = getattr(f.cliente, 'is_isento', False)
        capital_cliente = f.cliente.capital_alocado or 0.0
        
        if f.user_id not in rois_clientes:
            rois_clientes[f.user_id] = {
                'bruto_acumulado': 0.0, 
                'capital': capital_cliente,
                'dias_operados': set()
            }
            
        if f.user_id not in ranking_clientes:
            ranking_clientes[f.user_id] = {
                'nome': f.cliente.nome,
                'bruto': 0.0,
                'repasse': 0.0,
                'modelo': modelo_cliente,
                'is_isento': is_isento_cliente
            }
            
        for d in f.dias:
            if filtro_dia and d.data_pregao != dt_dia:
                continue
            if d.data_pregao.year != ano and (filtro_ano or not any([filtro_dia, filtro_semana_dia])):
                continue

            if d.status == 'relatorio_enviado':
                # Só calcula repasse DW se for modelo Comissão e não isento
                if modelo_cliente == 'comissao' and not is_isento_cliente:
                    faturamento_total += d.repasse
                    ranking_clientes[f.user_id]['repasse'] += d.repasse
                
                # Bruto Global contabiliza de todos (Compra e Comissão e Isentos)
                if d.bruto > 0:
                    faturamento_bruto_total += d.bruto
                    ranking_clientes[f.user_id]['bruto'] += d.bruto
                    rois_clientes[f.user_id]['bruto_acumulado'] += d.bruto
                    rois_clientes[f.user_id]['dias_operados'].add(d.data_pregao)
                    
                    # Gráfico foca apenas em dias de GAIN
                    dados_grafico_raw[d.data_pregao] = dados_grafico_raw.get(d.data_pregao, 0.0) + d.bruto

    datas_ordenadas = sorted(dados_grafico_raw.keys())
    chart_labels = [dt.strftime('%d/%m') for dt in datas_ordenadas]
    chart_data = [round(dados_grafico_raw[dt], 2) for dt in datas_ordenadas]

    lista_rois = []
    for uid, dados in rois_clientes.items():
        qtd_dias = len(dados['dias_operados'])
        if dados['capital'] > 0 and dados['bruto_acumulado'] != 0 and qtd_dias > 0:
            media_diaria_bruta = dados['bruto_acumulado'] / qtd_dias
            roi_cliente_diario = (media_diaria_bruta / dados['capital']) * 100
            lista_rois.append(roi_cliente_diario)

    if lista_rois:
        roi_min = min(lista_rois)
        roi_max = max(lista_rois)
        roi_med = sum(lista_rois) / len(lista_rois)
    else:
        roi_min = roi_med = roi_max = 0.0

    clientes_ativos = User.query.filter(
        User.role == 'cliente', 
        User.status_acesso == 'ativo',
        db.or_(User.is_isento == False, User.is_isento.is_(None))
    ).count()
    
    clientes_inativos = User.query.filter_by(role='cliente', status_acesso='inativo').count()
    
    alocado_row = db.session.query(db.func.sum(User.capital_alocado)).filter(
        User.role == 'cliente', 
        User.status_acesso == 'ativo', 
        db.or_(User.is_isento == False, User.is_isento.is_(None))
    ).first()
    
    capital_total = alocado_row[0] or 0.0
    
    lista_ranking = [c for c in ranking_clientes.values() if c['bruto'] > 0 or c['repasse'] > 0]
    lista_ranking.sort(key=lambda x: x['bruto'], reverse=True)
    
    return {
        'clientes_ativos': clientes_ativos,
        'clientes_inativos': clientes_inativos,
        'capital_total': capital_total,
        'faturamento_total': faturamento_total,
        'faturamento_bruto_total': faturamento_bruto_total,
        'label_periodo': label_periodo,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'roi_min': roi_min,
        'roi_med': roi_med,
        'roi_max': roi_max,
        'ranking_faturamento': lista_ranking
    }

def obter_dados_dashboard_cliente(user_id, filtro_dia, filtro_semana_dia, filtro_ano):
    """
    Processa a matemática do dashboard do parceiro: filtros de data, 
    faturamento bruto, faturamento líquido e média.
    """
    faturas_base = Fatura.query.filter_by(user_id=user_id).options(joinedload(Fatura.dias))
    
    if filtro_dia:
        dt_dia = datetime.strptime(filtro_dia, '%Y-%m-%d').date()
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio <= dt_dia, Fatura.data_fim >= dt_dia).all()
        label_periodo = f"Dia {dt_dia.strftime('%d/%m/%Y')}"
        
    elif filtro_semana_dia:
        dt_ref = datetime.strptime(filtro_semana_dia, '%Y-%m-%d').date()
        dias_para_sexta = (dt_ref.weekday() - 4) % 7
        dt_inicio_sem = dt_ref - timedelta(days=dias_para_sexta)
        dt_fim_sem = dt_inicio_sem + timedelta(days=6)
        
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_sem, Fatura.data_inicio <= dt_fim_sem).all()
        label_periodo = f"Ciclo {dt_inicio_sem.strftime('%d/%m')} a {dt_fim_sem.strftime('%d/%m/%Y')}"
        
    elif filtro_ano:
        ano = int(filtro_ano)
        dt_inicio_ano = datetime(ano, 1, 1).date()
        dt_fim_ano = datetime(ano, 12, 31).date()
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_ano, Fatura.data_inicio <= dt_fim_ano).all()
        label_periodo = f"Ano {ano}"
        
    else:
        faturas_filtradas = faturas_base.order_by(Fatura.data_inicio.desc()).limit(1).all()
        if faturas_filtradas:
            f = faturas_filtradas[0]
            label_periodo = f"Semana Atual ({f.data_inicio.strftime('%d/%m')} a {f.data_fim.strftime('%d/%m')})"
        else:
            faturas_filtradas = []
            label_periodo = "Semana Atual"

    bruto_total = 0.0
    liquido_total = 0.0
    dados_grafico_raw = {}

    for f in faturas_filtradas:
        for d in f.dias:
            if filtro_dia and d.data_pregao != dt_dia:
                continue
            if filtro_ano and d.data_pregao.year != int(filtro_ano):
                continue
                
            if d.status == 'relatorio_enviado':
                bruto_total += d.liquido_pregao
                liquido_total += d.liquido
                dados_grafico_raw[d.data_pregao] = dados_grafico_raw.get(d.data_pregao, 0.0) + d.liquido

    datas_ordenadas = sorted(dados_grafico_raw.keys())
    chart_labels = [dt.strftime('%d/%m') for dt in datas_ordenadas]
    chart_data = [round(dados_grafico_raw[dt], 2) for dt in datas_ordenadas]

    dias_unicos_operados = len(datas_ordenadas)
    media_diaria = (liquido_total / dias_unicos_operados) if dias_unicos_operados > 0 else 0.0
    
    user = User.query.get(user_id)
    eh_compra = (user.modelo_negocio == 'compra')
    # Para dashboard, usamos o modelo atual do usuário (não baseado em data), pois é uma visão agregada.
    # No entanto, os valores de repasse devem seguir a regra de migração? O dashboard mostra o lucro do cliente,
    # que para clientes compra é 100% do lucro líquido (já está correto).
    # Para clientes comissionados que migraram, o dashboard mostra apenas dados atuais (após migração),
    # então usar o modelo atual é suficiente.
    multiplicador = 1.0 if (getattr(user, 'is_isento', False) or eh_compra) else 0.70
    lucro_parceiro_total = liquido_total * multiplicador

    return {
        'bruto_total': bruto_total,
        'liquido_total': liquido_total,
        'lucro_parceiro_total': lucro_parceiro_total,
        'media_diaria': media_diaria,
        'label_periodo': label_periodo,
        'chart_labels': chart_labels,
        'chart_data': chart_data
    }