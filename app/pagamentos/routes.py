from flask import Blueprint
from flask_login import login_required

pagamentos_bp = Blueprint('pagamentos', __name__, url_prefix='/pagamentos')

@pagamentos_bp.route('/')
@login_required
def index():
    return "<h1>Módulo de Pagamentos: Em construção...</h1>"

