from app import create_app, db
from app.models import User
from werkzeug.security import generate_password_hash

app = create_app()

with app.app_context():
    cpf_admin = '00000000000' # Seu CPF de acesso (mude se quiser)
    senha_admin = 'admin123'  # Sua senha
    
    admin_existe = User.query.filter_by(role='admin').first()
    
    if not admin_existe:
        novo_admin = User(
            cpf=cpf_admin,
            password_hash=generate_password_hash(senha_admin),
            nome='Admin DW Capital',
            role='admin',
            status_acesso='ativo'
        )
        db.session.add(novo_admin)
        db.session.commit()
        print(f"✅ Admin criado com sucesso!\nCPF: {cpf_admin}\nSenha: {senha_admin}")
    else:
        print("⚠️ Já existe um admin cadastrado no banco.")

