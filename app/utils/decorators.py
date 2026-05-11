from functools import wraps
from flask import redirect, url_for
from flask_login import current_user, login_required

def admin_required(f):
    """
    Decorador que garante que a rota só seja acessada por administradores.
    Ele já embute a verificação de login_required para manter o código limpo.
    """
    @login_required
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            return redirect(url_for('client.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

