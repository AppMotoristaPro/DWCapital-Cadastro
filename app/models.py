from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime
import pytz
from sqlalchemy.orm import validates
from app.utils.validators import validar_cpf

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
    modelo_negocio = db.Column(db.String(20), default='comissao')
    
    endereco = db.Column(db.Text)
    email = db.Column(db.String(120))
    celular = db.Column(db.String(20))
    
    corretora = db.Column(db.String(50), nullable=True)
    capital_alocado = db.Column(db.Float, default=0.0)
    
    licenca_bloqueada = db.Column(db.Boolean, default=False)
    robot_acesso_bloqueado = db.Column(db.Boolean, default=False)
    setup_pago = db.Column(db.Boolean, default=False)
    setup_txid = db.Column(db.String(100), nullable=True)
    setup_payload = db.Column(db.Text, nullable=True)
    
    perfil_risco = db.Column(db.String(20))
    data_cadastro = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    matricula = db.Column(db.String(20), unique=True, nullable=True)
    precisa_trocar_senha = db.Column(db.Boolean, default=False)
    termo_assinado = db.Column(db.Boolean, default=False)
    docusign_envelope_id = db.Column(db.String(100), nullable=True)
    
    indicador_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_indicado = db.Column(db.Boolean, default=False)
    data_indicacao = db.Column(db.DateTime, nullable=True)
    
    produto_vitalicio_id = db.Column(db.Integer, db.ForeignKey('produto_robo.id'), nullable=True)
    produto_vitalicio = db.relationship('ProdutoRobo', foreign_keys=[produto_vitalicio_id])
    
    data_migracao_compra = db.Column(db.DateTime, nullable=True)
    
    # Relacionamentos
    indicado_por = db.relationship('User', remote_side=[id], backref='indicacoes')
    faturas = db.relationship('Fatura', backref='cliente', lazy=True, cascade="all, delete-orphan")
    alocacoes = db.relationship('AlocacaoCorretora', backref='cliente', lazy=True, cascade="all, delete-orphan")
    logs = db.relationship('LogAuditoria', backref='admin', lazy=True)
    documentos_extras = db.relationship('DocumentoCliente', backref='cliente', lazy=True, cascade="all, delete-orphan")
    parcelas_licenca = db.relationship('ParcelaCompra', backref='cliente', lazy=True, cascade="all, delete-orphan", order_by="ParcelaCompra.ordem")
    downloads = db.relationship('DownloadControle', backref='cliente', lazy=True, cascade="all, delete-orphan")
    licencas = db.relationship('LicencaCliente', backref='cliente', lazy=True, cascade="all, delete-orphan")
    
    # Contas MT5 – relacionamento corrigido
    contas_mt5 = db.relationship('ContaMT5Cliente', back_populates='usuario', lazy=True, cascade="all, delete-orphan")

    @validates('cpf')
    def validate_cpf(self, key, cpf):
        if cpf and not validar_cpf(cpf):
            raise ValueError("CPF inválido")
        return cpf


class ContaMT5Cliente(db.Model):
    """Conta MT5 associada a um cliente, com corretora e capital alocado."""
    __tablename__ = 'conta_mt5_cliente'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    numero_conta = db.Column(db.String(20), nullable=False)
    nome_corretora = db.Column(db.String(50), nullable=False)
    capital_alocado = db.Column(db.Float, default=0.0)
    ativo = db.Column(db.Boolean, default=True)
    bloqueada = db.Column(db.Boolean, default=False)
    data_cadastro = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))

    # Relacionamento com User – nome interno 'usuario'
    usuario = db.relationship('User', back_populates='contas_mt5')

    # Propriedade de compatibilidade para código que espera 'conta.user'
    @property
    def user(self):
        return self.usuario

    def __repr__(self):
        return f"<ContaMT5Cliente user={self.user_id} conta={self.numero_conta}>"


class ParcelaCompra(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ordem = db.Column(db.Integer, nullable=False)
    valor = db.Column(db.Float, nullable=False)
    data_vencimento = db.Column(db.Date, nullable=False)
    
    txid_pix = db.Column(db.String(100), nullable=True)
    payload_pix = db.Column(db.Text, nullable=True)
    
    status = db.Column(db.String(20), default='pendente')
    data_pagamento = db.Column(db.DateTime, nullable=True)
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))


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
    txid_pix = db.Column(db.String(100), nullable=True)
    payload_pix = db.Column(db.Text, nullable=True)
    
    status = db.Column(db.String(20), default='pendente')
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    dias = db.relationship('FaturaDiaria', backref='fatura_semanal', lazy=True, cascade="all, delete-orphan", order_by="FaturaDiaria.data_pregao")

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
    
    relatorio_html_url = db.Column(db.String(255), nullable=True)
    motivo_isencao = db.Column(db.String(50), default='')
    operacao_detectada = db.Column(db.Boolean, default=False)

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
    ip_address = db.Column(db.String(45), nullable=True)


class DocumentoTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False) 
    arquivo_local = db.Column(db.String(100), nullable=False)
    is_onboarding = db.Column(db.Boolean, default=False)
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    

class DocumentoCliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey('documento_template.id'), nullable=False)
    
    autentique_document_id = db.Column(db.String(100), nullable=True)
    link_assinatura = db.Column(db.String(255), nullable=True) 
    status = db.Column(db.String(20), default='na_fila') 
    
    data_envio = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    data_assinatura = db.Column(db.DateTime, nullable=True)

    template = db.relationship('DocumentoTemplate', backref='documentos_enviados')


class PremioSolicitacao(db.Model):
    __tablename__ = 'premio_solicitacao'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    data_solicitacao = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    status = db.Column(db.String(20), default='pendente')
    tipo_premio = db.Column(db.String(20), nullable=False)
    valor = db.Column(db.Float, default=1000.0)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    data_aprovacao = db.Column(db.DateTime, nullable=True)
    data_pagamento = db.Column(db.DateTime, nullable=True)
    observacao = db.Column(db.Text, nullable=True)
    
    user = db.relationship('User', foreign_keys=[user_id], backref='solicitacoes_premio')
    admin = db.relationship('User', foreign_keys=[admin_id])


class ProdutoRobo(db.Model):
    __tablename__ = 'produto_robo'
    
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    ordem = db.Column(db.Integer, default=0)
    ativo = db.Column(db.Boolean, default=True)
    codigo_algoritmo = db.Column(db.Integer, nullable=False, default=700)
    
    versoes = db.relationship('VersaoRobo', backref='produto', lazy=True)
    
    def __repr__(self):
        return f"<ProdutoRobo {self.slug}>"


class VersaoRobo(db.Model):
    __tablename__ = 'versao_robo'
    
    id = db.Column(db.Integer, primary_key=True)
    versao = db.Column(db.String(20), nullable=False)
    arquivo_url = db.Column(db.String(255), nullable=False)
    novidades = db.Column(db.Text, nullable=True)
    data_upload = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    publicada = db.Column(db.Boolean, default=False)
    extensao = db.Column(db.String(10), nullable=True)
    public_id = db.Column(db.String(255), nullable=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto_robo.id'), nullable=False)

    def __repr__(self):
        return f"<VersaoRobo {self.versao} (produto_id={self.produto_id})>"


class DownloadControle(db.Model):
    __tablename__ = 'download_controle'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    conta_mt5_id = db.Column(db.Integer, db.ForeignKey('conta_mt5_cliente.id'), nullable=False)
    versao_id = db.Column(db.Integer, db.ForeignKey('versao_robo.id', ondelete='RESTRICT'), nullable=False)
    data_download = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    ciclo_inicio = db.Column(db.Date, nullable=True)
    
    versao = db.relationship('VersaoRobo', backref='downloads')
    conta = db.relationship('ContaMT5Cliente', backref='downloads')

    __table_args__ = (
        db.UniqueConstraint('conta_mt5_id', 'versao_id', 'ciclo_inicio', name='_conta_versao_ciclo_uc'),
    )

    def __repr__(self):
        return f"<DownloadControle user={self.user_id} conta={self.conta_mt5_id} versao={self.versao_id} ciclo={self.ciclo_inicio}>"


class LicencaCliente(db.Model):
    __tablename__ = 'licenca_cliente'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    conta_mt5_id = db.Column(db.Integer, db.ForeignKey('conta_mt5_cliente.id'), nullable=False)
    chave_licenca = db.Column(db.String(100), nullable=False)
    data_geracao = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    ciclo_inicio = db.Column(db.Date, nullable=False)
    ciclo_fim = db.Column(db.Date, nullable=False)
    
    tipo = db.Column(db.String(20), nullable=False, default='semanal')
    data_expiracao = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='ativa')
    
    conta = db.relationship('ContaMT5Cliente', backref='licencas')

    __table_args__ = (
        db.UniqueConstraint('conta_mt5_id', 'ciclo_inicio', name='_conta_ciclo_uc'),
    )

    def __repr__(self):
        return f"<LicencaCliente user={self.user_id} conta={self.conta_mt5_id} tipo={self.tipo} ciclo={self.ciclo_inicio}>"


class Notificacao(db.Model):
    __tablename__ = 'notificacao'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    titulo = db.Column(db.String(200), nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(500), nullable=True)
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(tz_br))
    lida = db.Column(db.Boolean, default=False)
    tipo = db.Column(db.String(50), default='migracao')
    
    user = db.relationship('User', backref='notificacoes')
    
    def __repr__(self):
        return f"<Notificacao user={self.user_id} tipo={self.tipo}>"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))