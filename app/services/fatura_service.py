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
        while len(dias_uteis) < 5 and data_atual <= fim_ciclo:
            # Trava Temporal: Só adiciona o dia útil se for maior ou igual à data de entrada
            if data_atual.weekday() < 5 and data_atual >= data_cadastro:
                dias_uteis.append(data_atual)
            data_atual += timedelta(days=1)
            
        houve_alteracao = False
        
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
                    
        if houve_alteracao:
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()

def auto_gerar_ciclos_em_lote(users, data_base=None):
    """
    ARQUITETURA VIRTUAL: Gera APENAS a gaveta principal (Fatura) em lote para não sobrecarregar.
    Os dias diários agora são calculados virtualmente na tela e preenchidos sob demanda.
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
        
        if fim_ciclo < data_cadastro:
            continue
            
        if user.id not in mapa_faturas:
            nova_fatura = Fatura(
                user_id=user.id,
                data_inicio=inicio_ciclo,
                data_fim=fim_ciclo,
                status='pendente'
            )
            novas_faturas.append(nova_fatura)
    
    if novas_faturas:
        db.session.add_all(novas_faturas)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

