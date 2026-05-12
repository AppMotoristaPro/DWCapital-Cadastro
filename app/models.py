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
    
    is_isento = db.Column(db.Boolean, default=False)
    
    endereco = db.Column(db.Text)
    email = db.Column(db.String(120))
    celular = db.Column(db.String(20))
    
    corretora = db.Column(db.String(50), nullable=True)
    capital_alocado = db.Column(db.Float, default=0.0)
    
    perfil_risco = db.Column(db.String(20))
    data_cadastro = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    matricula = db.Column(db.String(20), unique=True, nullable=True)
    precisa_trocar_senha = db.Column(db.Boolean, default=False)
    termo_assinado = db.Column(db.Boolean, default=False)
    docusign_envelope_id = db.Column(db.String(100), nullable=True)
    
    faturas = db.relationship('Fatura', backref='cliente', lazy=True, cascade="all, delete-orphan")
    alocacoes = db.relationship('AlocacaoCorretora', backref='cliente', lazy=True, cascade="all, delete-orphan")
    logs = db.relationship('LogAuditoria', backref='admin', lazy=True)
    
    documentos_extras = db.relationship('DocumentoCliente', backref='cliente', lazy=True, cascade="all, delete-orphan")

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

    # INTELIGÊNCIA EMBUTIDA NO MODELO (Fat Model)
    def recalcular_totais(self):
        self.bruto = sum((d.bruto if d.bruto > 0 else 0.0) for d in self.dias if d.status == 'relatorio_enviado')
        self.taxas_b3 = sum((d.taxas_b3 if d.taxas_b3 > 0 else 0.0) for d in self.dias if d.status == 'relatorio_enviado')
        self.irrf_1 = sum((d.irrf_1 if d.irrf_1 > 0 else 0.0) for d in self.dias if d.status == 'relatorio_enviado')
        self.liquido_pregao = sum((d.liquido_pregao if d.liquido_pregao > 0 else 0.0) for d in self.dias if d.status == 'relatorio_enviado')
        self.irrf_19 = sum((d.irrf_19 if d.irrf_19 > 0 else 0.0) for d in self.dias if d.status == 'relatorio_enviado')
        self.liquido = sum((d.liquido if d.liquido > 0 else 0.0) for d in self.dias if d.status == 'relatorio_enviado')
        self.repasse = sum((d.repasse if d.repasse > 0 else 0.0) for d in self.dias if d.status == 'relatorio_enviado')
        
        dias_enviados = sum(1 for d in self.dias if d.status == 'relatorio_enviado')
        dias_isentos = sum(1 for d in self.dias if d.status == 'isento')
        total_exigido = len(self.dias) - dias_isentos
        
        if dias_enviados == 0:
            if total_exigido == 0 and len(self.dias) > 0:
                self.status = 'completo'
            else:
                self.status = 'pendente'
        elif dias_enviados >= total_exigido and total_exigido > 0:
            self.status = 'completo'
        else:
            self.status = 'parcial'

class FaturaDiaria(db.Model):
    __table_args__ = (db.UniqueConstraint('fatura_id', 'data_pregao', 'nome_corretora', name='_fatura_dia_corretora_uc'),)
    
    id = db.Column(db.Integer, primary_key=True)
    fatura_id = db.Column(db.Integer, db.ForeignKey('fatura.id'), nullable=False)
    nome_corretora = db.Column(db.String(50), nullable=True, default='GENIAL') 
    data_pregao = db.Column(db.Date, nullable=False)
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

    # INTELIGÊNCIA EMBUTIDA NO MODELO (Fat Model)
    def zerar_valores(self, isentar=False):
        self.arquivo_pdf = None
        self.bruto = 0.0
        self.taxas_b3 = 0.0
        self.irrf_1 = 0.0
        self.liquido_pregao = 0.0
        self.irrf_19 = 0.0
        self.liquido = 0.0
        self.repasse = 0.0
        if isentar:
            self.is_isento = True
            self.status = 'isento'
        else:
            self.is_isento = False
            self.status = 'pendente'

class LogAuditoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    admin_nome = db.Column(db.String(100), nullable=False)
    acao_detalhada = db.Column(db.Text, nullable=False)
    categoria = db.Column(db.String(50), nullable=False) 
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))

class DocumentoTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False) 
    arquivo_local = db.Column(db.String(100), nullable=False)
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    
class DocumentoCliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey('documento_template.id'), nullable=False)
    
    autentique_document_id = db.Column(db.String(100), nullable=False)
    link_assinatura = db.Column(db.String(255), nullable=True) 
    status = db.Column(db.String(20), default='pendente')
    
    data_envio = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    data_assinatura = db.Column(db.DateTime, nullable=True)

    template = db.relationship('DocumentoTemplate', backref='documentos_enviados')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

