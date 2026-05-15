from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload, contains_eager
from app import db
from app.models import Fatura, User
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')

def obter_dados_dashboard(filtro_dia, filtro_semana_dia, filtro_ano):
    """
    Processa toda a matemática do dashboard admin: filtros de data, 
    faturamento bruto/líquido, cálculo de ROI Diário Médio e agregação do gráfico.
    """
    # OTIMIZAÇÃO MAX: Traz os dados do Cliente e das Faturas Diárias na mesma consulta!
    faturas_base = Fatura.query.join(User).options(
        contains_eager(Fatura.cliente),
        joinedload(Fatura.dias)
    ).filter(
        Fatura.status.in_(['parcial', 'completo', 'pago', 'inadimplente']),
        db.or_(User.is_isento == False, User.is_isento.is_(None))
    )
    
    # CORREÇÃO: Variável de segurança inicializada no topo para evitar UnboundLocalError
    ano_atual = datetime.now(tz_br).year
    ano = ano_atual
    
    if filtro_dia:
        dt_dia = datetime.strptime(filtro_dia, '%Y-%m-%d').date()
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio <= dt_dia, Fatura.data_fim >= dt_dia).all()
        label_periodo = f"Dia {dt_dia.strftime('%d/%m/%Y')}"
        ano = dt_dia.year # Sincroniza o ano
        
    elif filtro_semana_dia:
        dt_ref = datetime.strptime(filtro_semana_dia, '%Y-%m-%d').date()
        dias_para_sexta = (dt_ref.weekday() - 4) % 7
        dt_inicio_sem = dt_ref - timedelta(days=dias_para_sexta)
        dt_fim_sem = dt_inicio_sem + timedelta(days=6)
        
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_sem, Fatura.data_inicio <= dt_fim_sem).all()
        label_periodo = f"Ciclo {dt_inicio_sem.strftime('%d/%m/%Y')} a {dt_fim_sem.strftime('%d/%m/%Y')}"
        ano = dt_inicio_sem.year # Sincroniza o ano
        
    elif filtro_ano:
        ano = int(filtro_ano)
        dt_inicio_ano = datetime(ano, 1, 1).date()
        dt_fim_ano = datetime(ano, 12, 31).date()
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_ano, Fatura.data_inicio <= dt_fim_ano).all()
        label_periodo = f"Ano {ano}"
        
    else:
        # AJUSTE: Se não tiver nenhum filtro, carrega o ano atual por padrão
        dt_inicio_ano = datetime(ano_atual, 1, 1).date()
        dt_fim_ano = datetime(ano_atual, 12, 31).date()
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_ano, Fatura.data_inicio <= dt_fim_ano).all()
        label_periodo = f"Ano {ano_atual}"
        
    # Inicializa variáveis para os cálculos granulares
    faturamento_total = 0.0
    faturamento_bruto_total = 0.0
    dados_grafico_raw = {}
    rois_clientes = {}

    for f in faturas_filtradas:
        capital_cliente = f.cliente.capital_alocado or 0.0
        
        if f.user_id not in rois_clientes:
            rois_clientes[f.user_id] = {
                'bruto_acumulado': 0.0, 
                'capital': capital_cliente,
                'dias_operados': set()
            }
            
        for d in f.dias:
            # Filtro granular por dia (se aplicável)
            if filtro_dia and d.data_pregao != dt_dia:
                continue
            # Filtro granular por ano (para garantir consistência na visão anual padrão)
            if d.data_pregao.year != ano and (filtro_ano or not any([filtro_dia, filtro_semana_dia])):
                continue

            if d.status == 'relatorio_enviado':
                faturamento_total += d.repasse
                
                # CORREÇÃO DO WIDGET BRUTO E ROI: Considera apenas dias de Gain (positivos)
                if d.bruto > 0:
                    faturamento_bruto_total += d.bruto
                    # O ROI agora também só soma os dias positivos
                    rois_clientes[f.user_id]['bruto_acumulado'] += d.bruto
                    rois_clientes[f.user_id]['dias_operados'].add(d.data_pregao)
                    
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
        'roi_max': roi_max
    }

def obter_dados_dashboard_cliente(user_id, filtro_dia, filtro_semana_dia, filtro_ano):
    """
    Processa a matemática do dashboard do parceiro: filtros de data, 
    faturamento bruto, faturamento líquido (sem taxa de 30%) e média.
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
                # AJUSTE MATEMÁTICO: Agora usando o Liquido do Pregão (já com taxas B3 descontadas)
                bruto_total += d.liquido_pregao
                liquido_total += d.liquido
                dados_grafico_raw[d.data_pregao] = dados_grafico_raw.get(d.data_pregao, 0.0) + d.liquido

    datas_ordenadas = sorted(dados_grafico_raw.keys())
    chart_labels = [dt.strftime('%d/%m') for dt in datas_ordenadas]
    chart_data = [round(dados_grafico_raw[dt], 2) for dt in datas_ordenadas]

    dias_unicos_operados = len(datas_ordenadas)
    media_diaria = (liquido_total / dias_unicos_operados) if dias_unicos_operados > 0 else 0.0
    
    # NOVA MÉTRICA: Lucro Limpo (70% do líquido operacional)
    # Nota: Se o usuário for isento (is_isento=True), o lucro limpo dele é 100% do líquido operacional.
    user = User.query.get(user_id)
    multiplicador = 1.0 if getattr(user, 'is_isento', False) else 0.70
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