from app import db
from app.models import Fatura, FaturaDiaria
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')

def atualizar_totais_semana(fatura):
    """Recalcula todos os valores de uma fatura semanal usando a inteligência do Modelo."""
    fatura.recalcular_totais()
    db.session.commit()

def auto_gerar_ciclo(user, data_base=None):
    """Gera automaticamente a gaveta da semana e os dias úteis APENAS para o investidor ativo na sessão."""
    if not user.alocacoes:
        return

    hoje = data_base if data_base else datetime.now(tz_br).date()
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6)
    
    data_cadastro = user.data_cadastro.date() if user.data_cadastro else datetime.min.date()
    
    # Trava Temporal: Não gera ciclo se a semana encerrou antes do cliente entrar
    if fim_ciclo < data_cadastro:
        return

    fatura_existente = Fatura.query.filter_by(user_id=user.id, data_inicio=inicio_ciclo).first()

    if not fatura_existente:
        nova_fatura = Fatura(
            user_id=user.id,
            data_inicio=inicio_ciclo,
            data_fim=fim_ciclo,
            status='pendente'
        )
        db.session.add(nova_fatura)
        
        try:
            db.session.commit()
            fatura_existente = nova_fatura
        except IntegrityError:
            db.session.rollback()
            fatura_existente = Fatura.query.filter_by(user_id=user.id, data_inicio=inicio_ciclo).first()
            if not fatura_existente:
                return

    if fatura_existente:
        dias_uteis = []
        data_atual = inicio_ciclo
        
        # FRENTE 1: Gera exatamente os 5 dias do ciclo, independentemente de quando o cliente entrou
        while len(dias_uteis) < 5 and data_atual <= fim_ciclo:
            if data_atual.weekday() < 5:
                dias_uteis.append(data_atual)
            data_atual += timedelta(days=1)
            
        houve_alteracao = False
        
        dias_existentes = FaturaDiaria.query.filter_by(fatura_id=fatura_existente.id).all()
        mapa_dias = {(d.data_pregao, d.nome_corretora) for d in dias_existentes}

        for data in dias_uteis:
            for alocacao in user.alocacoes:
                if (data, alocacao.nome_corretora) not in mapa_dias:
                    # FRENTE 2: Dias anteriores ao cadastro entram automaticamente como isentos
                    is_isento = data < data_cadastro
                    status_dia = 'isento' if is_isento else 'pendente'
                    
                    novo_dia = FaturaDiaria(
                        fatura_id=fatura_existente.id,
                        data_pregao=data,
                        nome_corretora=alocacao.nome_corretora,
                        status=status_dia,
                        is_isento=is_isento
                    )
                    db.session.add(novo_dia)
                    houve_alteracao = True
                    
        if houve_alteracao:
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()

def auto_gerar_ciclos_em_lote(users, data_base=None):
    """
    Gera a gaveta principal (Fatura) e todos os dias úteis do ciclo para cada cliente ativo.
    Deve ser executado por um job agendado (cron) para garantir que todos os dias existam,
    independentemente de o cliente acessar o portal.
    """
    if not users:
        return

    hoje = data_base if data_base else datetime.now(tz_br).date()
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6)

    # Gera os 5 dias úteis (segunda a sexta) do ciclo
    dias_uteis = []
    data_atual = inicio_ciclo
    while len(dias_uteis) < 5 and data_atual <= fim_ciclo:
        if data_atual.weekday() < 5:  # 0=segunda, 4=sexta
            dias_uteis.append(data_atual)
        data_atual += timedelta(days=1)

    user_ids = [u.id for u in users if u.alocacoes]
    if not user_ids:
        return

    # Busca faturas existentes para este ciclo
    faturas_existentes = Fatura.query.filter(
        Fatura.user_id.in_(user_ids),
        Fatura.data_inicio == inicio_ciclo
    ).all()
    mapa_faturas = {f.user_id: f for f in faturas_existentes}
    novas_faturas = []

    for user in users:
        if not user.alocacoes:
            continue

        data_cadastro = user.data_cadastro.date() if user.data_cadastro else datetime.min.date()

        # Não gera ciclo se a semana terminou antes do cliente entrar
        if fim_ciclo < data_cadastro:
            continue

        # Cria a fatura se não existir
        if user.id not in mapa_faturas:
            nova_fatura = Fatura(
                user_id=user.id,
                data_inicio=inicio_ciclo,
                data_fim=fim_ciclo,
                status='pendente'
            )
            db.session.add(nova_fatura)
            novas_faturas.append(nova_fatura)
            fatura_obj = nova_fatura
        else:
            fatura_obj = mapa_faturas[user.id]

        # --- CRIAÇÃO DOS DIAS DIÁRIOS (FaturaDiaria) ---
        # Verifica quais combinações (data, corretora) já existem
        dias_existentes = FaturaDiaria.query.filter_by(fatura_id=fatura_obj.id).all()
        mapa_dias = {(d.data_pregao, d.nome_corretora) for d in dias_existentes}

        for data in dias_uteis:
            for alocacao in user.alocacoes:
                if (data, alocacao.nome_corretora) not in mapa_dias:
                    is_isento = data < data_cadastro
                    status_dia = 'isento' if is_isento else 'pendente'
                    novo_dia = FaturaDiaria(
                        fatura_id=fatura_obj.id,
                        data_pregao=data,
                        nome_corretora=alocacao.nome_corretora,
                        status=status_dia,
                        is_isento=is_isento
                    )
                    db.session.add(novo_dia)

    # Persiste tudo de uma vez (faturas + dias)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()

# ==================== FUNÇÃO PARA DETERMINAR MODELO VIGENTE POR DATA ====================

def modelo_para_fatura(user, data_inicio_fatura):
    """
    Retorna o modelo de negócio que deve ser aplicado para uma fatura com determinada data de início.
    Se o usuário migrou para compra em uma data posterior, as faturas anteriores continuam como comissão.
    """
    if user.modelo_negocio == 'comissao':
        return 'comissao'
    if user.modelo_negocio == 'compra' and user.data_migracao_compra:
        if data_inicio_fatura < user.data_migracao_compra.date():
            return 'comissao'
    return 'compra'

# ==================== NOVA FUNÇÃO EXTRAÍDA DA ROTA /faturas ====================

def garantir_dias_faltantes_para_fatura(user, fatura):
    """
    Garante que a fatura tenha exatamente os 5 dias úteis da semana, sem sábados/domingos.
    Remove dias de fim de semana existentes e cria os dias que estão faltando para cada corretora.
    Retorna True se houve alguma alteração no banco, False caso contrário.
    """
    data_cadastro = user.data_cadastro.date() if user.data_cadastro else datetime.min.date()
    houve_alteracao = False

    # 1. Remove dias de fim de semana (sábado/domingo) que possam ter sido criados erroneamente
    for dia in list(fatura.dias):
        if dia.data_pregao.weekday() >= 5:  # sábado=5, domingo=6
            db.session.delete(dia)
            houve_alteracao = True

    # 2. Determina os 5 dias úteis da semana (segunda a sexta)
    dias_uteis = []
    data_atual = fatura.data_inicio
    while len(dias_uteis) < 5 and data_atual <= fatura.data_fim:
        if data_atual.weekday() < 5:
            dias_uteis.append(data_atual)
        data_atual += timedelta(days=1)

    # 3. Conjunto de (data, corretora) já existente
    dias_existentes = {(d.data_pregao, d.nome_corretora) for d in fatura.dias}

    # 4. Cria os dias faltantes
    for data in dias_uteis:
        for alocacao in user.alocacoes:
            if (data, alocacao.nome_corretora) not in dias_existentes:
                is_isento = data < data_cadastro
                status_dia = 'isento' if is_isento else 'pendente'
                novo_dia = FaturaDiaria(
                    fatura_id=fatura.id,
                    data_pregao=data,
                    nome_corretora=alocacao.nome_corretora,
                    status=status_dia,
                    is_isento=is_isento
                )
                db.session.add(novo_dia)
                houve_alteracao = True

    return houve_alteracao