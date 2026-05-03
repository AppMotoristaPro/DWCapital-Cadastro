from app import create_app, db
from app.models import User, Fatura
from werkzeug.security import generate_password_hash

# Inicializa o app para carregar as variáveis de ambiente (.env)
app = create_app()

with app.app_context():
    print("🧹 1. Apagando tabelas antigas no banco Neon...")
    db.drop_all()
    
    print("🏗️ 2. Recriando as tabelas com a estrutura exata do código...")
    db.create_all()
    
    print("🔐 3. Criando a conta de Administrador...")
    admin = User(
        cpf='00000000000',
        password_hash=generate_password_hash('admin123'),
        nome='Admin DW Capital',
        role='admin',
        status_acesso='ativo'
    )
    
    db.session.add(admin)
    db.session.commit()
    
    print("✅ Sucesso Absoluto! Banco sincronizado e Admin injetado.")

