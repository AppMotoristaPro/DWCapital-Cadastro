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
    
    # Define se o cliente/parceiro é isento da cobrança de repasse (30%)
    is_isento = db.Column(db.Boolean, default=False)
    
    endereco = db.Column(db.Text)
    email = db.Column(db.String(120))
    celular = db.Column(db.String(20))
    
    # MANTIDOS TEMPORARIAMENTE PARA A MIGRAÇÃO SEGURA
    corretora = db.Column(db.String(50), nullable=True)
    capital_alocado = db.Column(db.Float, default=0.0)
    
    perfil_risco = db.Column(db.String(20))
    data_cadastro = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    matricula = db.Column(db.String(20), unique=True, nullable=True)
    precisa_trocar_senha = db.Column(db.Boolean, default=False)
    termo_assinado = db.Column(db.Boolean, default=False)
    docusign_envelope_id = db.Column(db.String(100), nullable=True)
    
    # RELACIONAMENTOS ATUALIZADOS
    faturas = db.relationship('Fatura', backref='cliente', lazy=True, cascade="all, delete-orphan")
    alocacoes = db.relationship('AlocacaoCorretora', backref='cliente', lazy=True, cascade="all, delete-orphan")
    
    # RELACIONAMENTO DE AUDITORIA (Logs gerados por este usuário/admin)
    logs = db.relationship('LogAuditoria', backref='admin', lazy=True)

# NOVA TABELA: Multi-Corretoras por Cliente
class AlocacaoCorretora(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    nome_corretora = db.Column(db.String(50), nullable=False)
    capital_alocado = db.Column(db.Float, default=0.0)
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))

class Fatura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    data_inicio = db.Column(db.Date, nullable=False)
    data_fim = db.Column(db.Date, nullable=False)
    bruto = db.Column(db.Float, default=0.0)
    taxas_b3 = db.Column(db.Float, default=0.0)
    irrf_1 = db.Column(db.Float, default=0.0)
    liquido_pregao = db.Column(db.Float, default=0.0)
    irrf_19 = db.Column(db.Float, default=0.0)
    liquido = db.Column(db.Float, default=0.0)
    repasse = db.Column(db.Float, default=0.0)
    comprovante_pix = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='pendente')
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    dias = db.relationship('FaturaDiaria', backref='fatura_semanal', lazy=True, cascade="all, delete-orphan", order_by="FaturaDiaria.data_pregao")

class FaturaDiaria(db.Model):
    # TRAVA DE SEGURANÇA: Impede duplicidade de corretora/data na mesma fatura no nível do banco
    __table_args__ = (db.UniqueConstraint('fatura_id', 'data_pregao', 'nome_corretora', name='_fatura_dia_corretora_uc'),)
    
    id = db.Column(db.Integer, primary_key=True)
    fatura_id = db.Column(db.Integer, db.ForeignKey('fatura.id'), nullable=False)
    
    # Para saber de qual corretora é este PDF
    nome_corretora = db.Column(db.String(50), nullable=True, default='GENIAL') 
    
    data_pregao = db.Column(db.Date, nullable=False)
    
    # NOVA COLUNA: Define se este pregão específico foi perdoado (ex: Feriado)
    is_isento = db.Column(db.Boolean, default=False)
    
    bruto = db.Column(db.Float, default=0.0)
    taxas_b3 = db.Column(db.Float, default=0.0)
    irrf_1 = db.Column(db.Float, default=0.0)
    liquido_pregao = db.Column(db.Float, default=0.0)
    irrf_19 = db.Column(db.Float, default=0.0)
    liquido = db.Column(db.Float, default=0.0)
    repasse = db.Column(db.Float, default=0.0)
    arquivo_pdf = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='pendente')

# NOVA TABELA: Cofre de Logs (Auditoria)
class LogAuditoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    admin_nome = db.Column(db.String(100), nullable=False)
    acao_detalhada = db.Column(db.Text, nullable=False)
    categoria = db.Column(db.String(50), nullable=False) # Ex: 'Pagamentos', 'Clientes', 'Segurança'
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

