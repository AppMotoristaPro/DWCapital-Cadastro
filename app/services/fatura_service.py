from app import db
from app.models import Fatura, FaturaDiaria
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')

def atualizar_totais_semana(fatura):
    """Recalcula todos os valores de uma fatura semanal com base nos dias processados."""
    fatura.bruto = sum((d.bruto if d.bruto > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.taxas_b3 = sum((d.taxas_b3 if d.taxas_b3 > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.irrf_1 = sum((d.irrf_1 if d.irrf_1 > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.liquido_pregao = sum((d.liquido_pregao if d.liquido_pregao > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.irrf_19 = sum((d.irrf_19 if d.irrf_19 > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.liquido = sum((d.liquido if d.liquido > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.repasse = sum((d.repasse if d.repasse > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    
    dias_enviados = sum(1 for d in fatura.dias if d.status == 'relatorio_enviado')
    dias_isentos = sum(1 for d in fatura.dias if d.status == 'isento')
    total_exigido = len(fatura.dias) - dias_isentos
    
    if dias_enviados == 0:
        if total_exigido == 0 and len(fatura.dias) > 0:
            fatura.status = 'completo'
        else:
            fatura.status = 'pendente'
    elif dias_enviados >= total_exigido and total_exigido > 0:
        fatura.status = 'completo'
    else:
        fatura.status = 'parcial'
        
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

