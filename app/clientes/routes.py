from flask import Blueprint
from flask_login import login_required

clientes_bp = Blueprint('clientes', __name__, url_prefix='/clientes')

@clientes_bp.route('/')
@login_required
def index():
    return "<h1>Módulo de Clientes: Em construção...</h1>"

