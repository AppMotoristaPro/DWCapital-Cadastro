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


def auto_gerar_ciclo(user, data_base=None, alocacoes_especificas=None):
    """
    Gera automaticamente a gaveta da semana e os dias úteis APENAS para o investidor ativo na sessão.
    Se alocacoes_especificas for passado (lista de AlocacaoCorretora), processa apenas essas alocações.
    
    CORREÇÃO: Agora NUNCA remove dias existentes. Apenas adiciona os que faltam.
    Isso preserva dados inseridos manualmente (via SQL) ou por outras fontes.
    """
    if not user.alocacoes:
        return

    hoje = data_base if data_base else datetime.now(tz_br).date()
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6)

    data_cadastro_global = user.data_cadastro.date() if user.data_cadastro else datetime.min.date()

    if fim_ciclo < data_cadastro_global:
        return

    # Define as alocações a serem processadas
    alocacoes = alocacoes_especificas if alocacoes_especificas is not None else user.alocacoes
    if not alocacoes:
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
        while len(dias_uteis) < 5 and data_atual <= fim_ciclo:
            if data_atual.weekday() < 5:
                dias_uteis.append(data_atual)
            data_atual += timedelta(days=1)

        houve_alteracao = False

        # Mapeia os dias já existentes na fatura
        dias_existentes = FaturaDiaria.query.filter_by(fatura_id=fatura_existente.id).all()
        mapa_dias = {(d.data_pregao, d.nome_corretora) for d in dias_existentes}

        # ========== CORREÇÃO: PRESERVAR TODOS OS DIAS EXISTENTES ==========
        # Apenas adiciona dias faltantes, NUNCA remove existentes
        # ===================================================================
        
        for data in dias_uteis:
            for alocacao in alocacoes:
                data_criacao_aloc = alocacao.data_criacao.date() if alocacao.data_criacao else data_cadastro_global

                # Se a data do pregão for anterior à data de criação da alocação, ignorar (não criar)
                if data < data_criacao_aloc:
                    # NÃO remove dias existentes mesmo que sejam anteriores à criação da alocação
                    # Isso preserva dados que foram inseridos manualmente
                    continue

                # Se o dia não existir, cria
                if (data, alocacao.nome_corretora) not in mapa_dias:
                    is_isento = data < data_cadastro_global
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
    Deve ser executado por um job agendado (cron) para garantir que todos os dias existam.
    
    CORREÇÃO: Agora NUNCA remove dias existentes. Apenas adiciona os que faltam.
    """
    if not users:
        return

    hoje = data_base if data_base else datetime.now(tz_br).date()
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6)

    dias_uteis = []
    data_atual = inicio_ciclo
    while len(dias_uteis) < 5 and data_atual <= fim_ciclo:
        if data_atual.weekday() < 5:
            dias_uteis.append(data_atual)
        data_atual += timedelta(days=1)

    user_ids = [u.id for u in users if u.alocacoes]
    if not user_ids:
        return

    faturas_existentes = Fatura.query.filter(
        Fatura.user_id.in_(user_ids),
        Fatura.data_inicio == inicio_ciclo
    ).all()
    mapa_faturas = {f.user_id: f for f in faturas_existentes}

    for user in users:
        if not user.alocacoes:
            continue

        data_cadastro_global = user.data_cadastro.date() if user.data_cadastro else datetime.min.date()

        if fim_ciclo < data_cadastro_global:
            continue

        if user.id not in mapa_faturas:
            nova_fatura = Fatura(
                user_id=user.id,
                data_inicio=inicio_ciclo,
                data_fim=fim_ciclo,
                status='pendente'
            )
            db.session.add(nova_fatura)
            fatura_obj = nova_fatura
        else:
            fatura_obj = mapa_faturas[user.id]

        dias_existentes = FaturaDiaria.query.filter_by(fatura_id=fatura_obj.id).all()
        mapa_dias = {(d.data_pregao, d.nome_corretora) for d in dias_existentes}

        for data in dias_uteis:
            for alocacao in user.alocacoes:
                data_criacao_aloc = alocacao.data_criacao.date() if alocacao.data_criacao else data_cadastro_global

                # Se a data for anterior à criação da alocação, NÃO remove existentes
                if data < data_criacao_aloc:
                    # Apenas ignora, não remove
                    continue

                # Se não existir, cria
                if (data, alocacao.nome_corretora) not in mapa_dias:
                    is_isento = data < data_cadastro_global
                    status_dia = 'isento' if is_isento else 'pendente'
                    novo_dia = FaturaDiaria(
                        fatura_id=fatura_obj.id,
                        data_pregao=data,
                        nome_corretora=alocacao.nome_corretora,
                        status=status_dia,
                        is_isento=is_isento
                    )
                    db.session.add(novo_dia)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


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


def garantir_dias_faltantes_para_fatura(user, fatura):
    """
    Garante que a fatura tenha os dias úteis da semana.
    
    CORREÇÃO: NUNCA remove dias existentes, apenas adiciona os faltantes.
    Preserva dados inseridos manualmente (via SQL) ou por outras fontes.
    """
    data_cadastro_global = user.data_cadastro.date() if user.data_cadastro else datetime.min.date()
    houve_alteracao = False

    # ========== CORREÇÃO: NÃO REMOVER DIAS DE FIM DE SEMANA ==========
    # Se existirem dias de fim de semana, eles são mantidos (podem ter sido inseridos manualmente)
    # ===================================================================
    
    # Determina os 5 dias úteis da semana (segunda a sexta)
    dias_uteis = []
    data_atual = fatura.data_inicio
    while len(dias_uteis) < 5 and data_atual <= fatura.data_fim:
        if data_atual.weekday() < 5:
            dias_uteis.append(data_atual)
        data_atual += timedelta(days=1)

    # Conjunto de (data, corretora) já existente
    dias_existentes = {(d.data_pregao, d.nome_corretora) for d in fatura.dias}

    # Para cada alocação, verifica quais dias devem existir e adiciona os faltantes
    for alocacao in user.alocacoes:
        data_criacao_aloc = alocacao.data_criacao.date() if alocacao.data_criacao else data_cadastro_global

        for data in dias_uteis:
            # Se a data for anterior à criação da alocação, ignora (não cria e não remove)
            if data < data_criacao_aloc:
                continue

            # Se não existir, cria
            if (data, alocacao.nome_corretora) not in dias_existentes:
                is_isento = data < data_cadastro_global
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
