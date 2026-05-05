from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    cpf = db.Column(db.String(11), unique=True, nullable=True)
    username = db.Column(db.String(50), unique=True, nullable=True)
    password_hash = db.Column(db.String(255))
    nome = db.Column(db.String(100))
    role = db.Column(db.String(10), default='cliente')
    status_acesso = db.Column(db.String(20), default='pendente_cadastro')
    endereco = db.Column(db.Text)
    email = db.Column(db.String(120))
    celular = db.Column(db.String(20))
    corretora = db.Column(db.String(50))
    capital_alocado = db.Column(db.Float, default=0.0)
    perfil_risco = db.Column(db.String(20))
    data_cadastro = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    matricula = db.Column(db.String(20), unique=True, nullable=True)
    
    # CAMPOS DOCUSIGN
    termo_assinado = db.Column(db.Boolean, default=False)
    docusign_envelope_id = db.Column(db.String(100), nullable=True)
    
    faturas = db.relationship('Fatura', backref='cliente', lazy=True, cascade="all, delete-orphan")

class Fatura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    data_inicio = db.Column(db.Date, nullable=False)
    data_fim = db.Column(db.Date, nullable=False)
    
    # NOVAS COLUNAS DA SEMANA
    bruto = db.Column(db.Float, default=0.0)
    taxas_b3 = db.Column(db.Float, default=0.0)
    irrf_1 = db.Column(db.Float, default=0.0)
    liquido_pregao = db.Column(db.Float, default=0.0)
    irrf_19 = db.Column(db.Float, default=0.0)
    liquido = db.Column(db.Float, default=0.0)
    repasse = db.Column(db.Float, default=0.0)
    
    status = db.Column(db.String(20), default='pendente')
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    dias = db.relationship('FaturaDiaria', backref='fatura_semanal', lazy=True, cascade="all, delete-orphan", order_by="FaturaDiaria.data_pregao")

class FaturaDiaria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fatura_id = db.Column(db.Integer, db.ForeignKey('fatura.id'), nullable=False)
    data_pregao = db.Column(db.Date, nullable=False)
    
    # NOVAS COLUNAS DO DIA
    bruto = db.Column(db.Float, default=0.0)
    taxas_b3 = db.Column(db.Float, default=0.0)
    irrf_1 = db.Column(db.Float, default=0.0)
    liquido_pregao = db.Column(db.Float, default=0.0)
    irrf_19 = db.Column(db.Float, default=0.0)
    liquido = db.Column(db.Float, default=0.0)
    repasse = db.Column(db.Float, default=0.0)
    
    arquivo_pdf = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='pendente')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

