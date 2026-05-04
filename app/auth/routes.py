@auth_bp.route('/primeiro_acesso', methods=['GET', 'POST'])
def primeiro_acesso():
    if request.method == 'POST':
        cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
        user = User.query.filter_by(cpf=cpf, status_acesso='pendente_cadastro').first()

        if user:
            user.nome = request.form.get('nome')
            user.email = request.form.get('email')
            user.celular = request.form.get('celular')
            user.endereco = request.form.get('endereco')
            user.corretora = request.form.get('corretora')
            user.capital_alocado = float(request.form.get('capital') or 0.0)
            user.password_hash = generate_password_hash(request.form.get('senha'))
            user.status_acesso = 'ativo'
            
            db.session.commit()
            flash('Cadastro concluído com sucesso! Bem-vindo à DW Capital.', 'success')
            return redirect(url_for('auth.login'))
        
        flash('CPF não liberado ou cadastro já ativo.', 'error')

    return render_template('auth/primeiro_acesso.html')

