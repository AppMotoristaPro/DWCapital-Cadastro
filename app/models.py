from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    cpf = db.Column(db.String(11), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))
    nome = db.Column(db.String(100))
    role = db.Column(db.String(10), default='cliente')
    status_acesso = db.Column(db.String(20), default='pendente_cadastro')
    corretora = db.Column(db.String(50))
    capital_alocado = db.Column(db.Float)
    perfil_risco = db.Column(db.String(20))
    faturas = db.relationship('Fatura', backref='cliente', lazy=True)

class Fatura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    data_inicio = db.Column(db.Date, nullable=False)
    data_fim = db.Column(db.Date, nullable=False)
    # Campos do Holerite
    bruto = db.Column(db.Float, default=0.0)      # Ajuste Day Trade
    irrf_1 = db.Column(db.Float, default=0.0)     # Dedo duro
    taxas_b3 = db.Column(db.Float, default=0.0)   # Emolumentos + Registro
    liquido = db.Column(db.Float, default=0.0)    # Líquido da Nota
    repasse = db.Column(db.Float, default=0.0)    # 30% da DW
    
    status = db.Column(db.String(20), default='pendente')
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

