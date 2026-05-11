from datetime import datetime, timedelta
from app import db
from app.models import Fatura, User

def obter_dados_dashboard(filtro_dia, filtro_semana_dia, filtro_ano):
    """
    Processa toda a matemática do dashboard admin: filtros de data, 
    faturamento bruto/líquido, cálculo de ROI e agregação do gráfico.
    """
    faturas_base = Fatura.query.join(User).filter(
        Fatura.status.in_(['parcial', 'completo', 'pago', 'inadimplente']),
        db.or_(User.is_isento == False, User.is_isento.is_(None))
    )
    
    label_periodo = "Todo o Período"
    
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
        label_periodo = f"Ciclo {dt_inicio_sem.strftime('%d/%m/%Y')} a {dt_fim_sem.strftime('%d/%m/%Y')}"
        
    elif filtro_ano:
        ano = int(filtro_ano)
        dt_inicio_ano = datetime(ano, 1, 1).date()
        dt_fim_ano = datetime(ano, 12, 31).date()
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_ano, Fatura.data_inicio <= dt_fim_ano).all()
        label_periodo = f"Ano {ano}"
        
    else:
        faturas_filtradas = faturas_base.all()
        
    faturamento_total = sum(f.repasse for f in faturas_filtradas)
    faturamento_bruto_total = sum(f.bruto for f in faturas_filtradas)
    
    dados_grafico_raw = {}
    rois_clientes = {}

    for f in faturas_filtradas:
        capital_cliente = f.cliente.capital_alocado or 0.0
        
        if f.user_id not in rois_clientes:
            rois_clientes[f.user_id] = {'bruto_acumulado': 0.0, 'capital': capital_cliente}
            
        rois_clientes[f.user_id]['bruto_acumulado'] += f.bruto

        for d in f.dias:
            if d.status == 'relatorio_enviado' and d.bruto != 0:
                dados_grafico_raw[d.data_pregao] = dados_grafico_raw.get(d.data_pregao, 0.0) + d.bruto

    datas_ordenadas = sorted(dados_grafico_raw.keys())
    chart_labels = [dt.strftime('%d/%m') for dt in datas_ordenadas]
    chart_data = [round(dados_grafico_raw[dt], 2) for dt in datas_ordenadas]

    lista_rois = []
    for uid, dados in rois_clientes.items():
        if dados['capital'] > 0 and dados['bruto_acumulado'] != 0:
            roi_cliente = (dados['bruto_acumulado'] / dados['capital']) * 100
            lista_rois.append(roi_cliente)

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
    
    qtd_faturas = len(faturas_filtradas)
    media_cliente = faturamento_bruto_total / qtd_faturas if qtd_faturas > 0 else 0.0
    
    return {
        'clientes_ativos': clientes_ativos,
        'clientes_inativos': clientes_inativos,
        'capital_total': capital_total,
        'faturamento_total': faturamento_total,
        'faturamento_bruto_total': faturamento_bruto_total,
        'media_cliente': media_cliente,
        'label_periodo': label_periodo,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'roi_min': roi_min,
        'roi_med': roi_med,
        'roi_max': roi_max
    }

