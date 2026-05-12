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

        for data in dias_uteis:
            for alocacao in user.alocacoes:
                existe = FaturaDiaria.query.filter_by(fatura_id=fatura_existente.id, data_pregao=data, nome_corretora=alocacao.nome_corretora).first()
                if not existe:
                    novo_dia = FaturaDiaria(
                        fatura_id=fatura_existente.id,
                        data_pregao=data,
                        nome_corretora=alocacao.nome_corretora,
                        status='pendente'
                    )
                    db.session.add(novo_dia)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

