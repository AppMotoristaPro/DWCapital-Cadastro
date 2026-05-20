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
    """Gera automaticamente a gaveta da semana e os dias úteis para o investidor."""
    if not user.alocacoes:
        return

    hoje = data_base if data_base else datetime.now(tz_br).date()
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6)

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
        
        # OTIMIZAÇÃO: Evita N+1 dentro da própria rotina individual
        dias_existentes = FaturaDiaria.query.filter_by(fatura_id=fatura_existente.id).all()
        mapa_dias = {(d.data_pregao, d.nome_corretora) for d in dias_existentes}

        for data in dias_uteis:
            for alocacao in user.alocacoes:
                if (data, alocacao.nome_corretora) not in mapa_dias:
                    novo_dia = FaturaDiaria(
                        fatura_id=fatura_existente.id,
                        data_pregao=data,
                        nome_corretora=alocacao.nome_corretora,
                        status='pendente'
                    )
                    db.session.add(novo_dia)
                    houve_alteracao = True
                    
        # 🚀 OTIMIZAÇÃO (Item 2): Apenas 1 commit ao final das inserções de dias
        if houve_alteracao:
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()

def auto_gerar_ciclos_em_lote(users, data_base=None):
    """
    Gera gavetas e dias úteis para múltiplos investidores com MÁXIMA eficiência.
    Resolve o gargalo de I/O agrupando todas as escritas em um único commit.
    """
    if not users:
        return

    hoje = data_base if data_base else datetime.now(tz_br).date()
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6)

    user_ids = [u.id for u in users if u.alocacoes]
    if not user_ids:
        return

    # 1. Busca todas as faturas existentes em UMA única query
    faturas_existentes = Fatura.query.filter(
        Fatura.user_id.in_(user_ids),
        Fatura.data_inicio == inicio_ciclo
    ).all()
    
    mapa_faturas = {f.user_id: f for f in faturas_existentes}
    novas_faturas = []

    # 2. Prepara as faturas que faltam na memória
    for user in users:
        if not user.alocacoes:
            continue
        if user.id not in mapa_faturas:
            nova_fatura = Fatura(
                user_id=user.id,
                data_inicio=inicio_ciclo,
                data_fim=fim_ciclo,
                status='pendente'
            )
            novas_faturas.append(nova_fatura)
    
    # 🚀 OTIMIZAÇÃO (Item 2): Commit em lote para todas as faturas faltantes
    if novas_faturas:
        db.session.add_all(novas_faturas)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
        
        # Recarrega para obter os IDs gerados pelo banco de dados
        faturas_existentes = Fatura.query.filter(
            Fatura.user_id.in_(user_ids),
            Fatura.data_inicio == inicio_ciclo
        ).all()
        mapa_faturas = {f.user_id: f for f in faturas_existentes}

    # 3. Preparar dias úteis do ciclo
    dias_uteis = []
    data_atual = inicio_ciclo
    while len(dias_uteis) < 5 and data_atual <= fim_ciclo:
        if data_atual.weekday() < 5:
            dias_uteis.append(data_atual)
        data_atual += timedelta(days=1)

    # 4. Busca todos os dias já existentes em UMA única query
    fatura_ids = [f.id for f in mapa_faturas.values()]
    dias_existentes = []
    if fatura_ids:
        dias_existentes = FaturaDiaria.query.filter(FaturaDiaria.fatura_id.in_(fatura_ids)).all()
    
    mapa_dias = {(d.fatura_id, d.data_pregao, d.nome_corretora) for d in dias_existentes}
    novos_dias = []

    # 5. Prepara os dias faltantes na memória
    for user in users:
        fatura = mapa_faturas.get(user.id)
        if not fatura:
            continue
        
        for data in dias_uteis:
            for alocacao in user.alocacoes:
                chave = (fatura.id, data, alocacao.nome_corretora)
                if chave not in mapa_dias:
                    novo_dia = FaturaDiaria(
                        fatura_id=fatura.id,
                        data_pregao=data,
                        nome_corretora=alocacao.nome_corretora,
                        status='pendente'
                    )
                    novos_dias.append(novo_dia)
                    mapa_dias.add(chave) # Adiciona no set para evitar duplicatas em memória
                    
    # 🚀 OTIMIZAÇÃO (Item 2): Commit em lote para todos os dias faltantes de toda a base
    if novos_dias:
        db.session.add_all(novos_dias)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

