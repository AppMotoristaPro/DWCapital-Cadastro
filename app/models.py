from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime
import pytz

# Fuso horário de Brasília
tz_br = pytz.timezone('America/Sao_Paulo')

class Admin(db.Model, UserMixin):
    """Tabela de uso exclusivo da DW Capital para login no sistema."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    nome = db.Column(db.String(100))

class Cliente(db.Model):
    """Registro de CRM do cliente gerido pela plataforma."""
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(120))
    celular = db.Column(db.String(20))
    data_cadastro = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    valor_alocado = db.Column(db.Float, default=0.0)
    corretora = db.Column(db.String(50)) # BTG, Genial, XP
    status = db.Column(db.String(20), default='ativo') # ativo, inativo
    faturas = db.relationship('Fatura', backref='cliente', lazy=True, cascade="all, delete-orphan")

class Fatura(db.Model):
    """Registros semanais de faturamento e repasse."""
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    data_inicio = db.Column(db.Date, nullable=False)
    data_fim = db.Column(db.Date, nullable=False)
    
    # Apuração
    bruto = db.Column(db.Float, default=0.0)
    irrf_1 = db.Column(db.Float, default=0.0)
    taxas_b3 = db.Column(db.Float, default=0.0)
    liquido = db.Column(db.Float, default=0.0)
    repasse = db.Column(db.Float, default=0.0)
    
    status = db.Column(db.String(20), default='pendente') # pendente, quitado, inadimplente
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))

@login_manager.user_loader
def load_user(user_id):
    # O sistema agora só loga o Admin
    return Admin.query.get(int(user_id))

