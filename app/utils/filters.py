import pytz
from datetime import datetime

def format_brl(value):
    """Formata um valor float para Reais (R$ 1.000,00)"""
    try:
        if value is None or value == "":
            num = 0.0
        else:
            num = float(value)
    except (ValueError, TypeError):
        num = 0.0
        
    return f"{num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def to_tz_br(dt):
    """Converte um datetime UTC do banco para o horário de Brasília."""
    if not isinstance(dt, datetime):
        return dt
    
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
        
    tz_br = pytz.timezone('America/Sao_Paulo')
    return dt.astimezone(tz_br)

