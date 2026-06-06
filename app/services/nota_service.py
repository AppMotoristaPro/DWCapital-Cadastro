import os
import tempfile
from werkzeug.utils import secure_filename
import cloudinary.uploader
from app import db
from app.utils.parsers.gerenciador_pdf import processar_pdf
from app.utils.validators import validar_pdf_mime
from app.services.fatura_service import atualizar_totais_semana
from app.models import FaturaDiaria

def processar_upload_nota(user, dia_id, arquivo, senha_manual=None):
    """
    Processa o upload de uma nota de corretagem (PDF).

    Args:
        user: Objeto User (cliente logado)
        dia_id: ID do FaturaDiaria a ser atualizado
        arquivo: FileStorage do Flask (request.files['relatorio_pdf'])
        senha_manual: Senha fornecida pelo usuário (opcional, para PDFs protegidos)

    Returns:
        dict com os campos:
            - success (bool)
            - error (str, opcional) - códigos: 'PDF_INVALIDO', 'REQUER_SENHA',
              'RELATORIO_INVALIDO', 'ERRO_TECNICO'
            - message (str, opcional)
    """
    # 1. Validações iniciais
    if not arquivo or not arquivo.filename:
        return {
            'success': False,
            'error': 'ARQUIVO_NAO_ENVIADO',
            'message': 'Nenhum arquivo foi enviado.'
        }

    if not validar_pdf_mime(arquivo):
        return {
            'success': False,
            'error': 'PDF_INVALIDO',
            'message': 'Arquivo não é um PDF válido (assinatura %PDF não encontrada).'
        }

    # 2. Buscar o dia e verificar permissão
    dia = FaturaDiaria.query.get(dia_id)
    if not dia or dia.fatura_semanal.user_id != user.id:
        return {
            'success': False,
            'error': 'ERRO_SEGURANCA',
            'message': 'Acesso negado.'
        }

    # 3. Salvar temporariamente o arquivo
    nome_seguro = secure_filename(arquivo.filename)
    upload_folder = tempfile.gettempdir()  # pasta temporária do sistema
    file_path = os.path.join(upload_folder, nome_seguro)
    arquivo.save(file_path)

    try:
        # 4. Processar o PDF (extrair dados via parser)
        dados = processar_pdf(file_path, dia.nome_corretora, user.cpf, senha_manual)
        if not dados:
            return {
                'success': False,
                'error': 'RELATORIO_INVALIDO',
                'message': 'Não foi possível ler os dados do PDF.'
            }

        # 5. Upload para Cloudinary
        upload_res = cloudinary.uploader.upload(file_path, folder="dwcapital/relatorios")
        dia.arquivo_pdf = upload_res.get('secure_url')

        # 6. Atualizar o registro do dia
        dia.bruto = dados.get('bruto')
        dia.taxas_b3 = dados.get('taxas_b3')
        dia.irrf_1 = dados.get('irrf_1')
        dia.liquido_pregao = dados.get('liquido_pregao')
        dia.irrf_19 = dados.get('irrf_19')
        dia.liquido = dados.get('liquido_dia')

        if getattr(user, 'is_isento', False):
            dia.repasse = 0.0
        else:
            dia.repasse = dados.get('repasse_dw')

        dia.status = 'relatorio_enviado'

        # 7. Commit e atualização da fatura
        db.session.commit()
        atualizar_totais_semana(dia.fatura_semanal)

        return {'success': True}

    except Exception as e:
        # Tratamento de erros específicos
        error_msg = str(e)
        if "SENHA_INCORRETA" in error_msg:
            return {
                'success': False,
                'error': 'REQUER_SENHA',
                'message': 'PDF protegido por senha. Informe a senha.'
            }
        if "PDF_INCOMPATIVEL" in error_msg:
            # Extrai a mensagem amigável (ex: "O arquivo enviado não pertence à XP Investimentos.")
            friendly_msg = error_msg.split("PDF_INCOMPATIVEL: ")[-1] if "PDF_INCOMPATIVEL: " in error_msg else error_msg
            return {
                'success': False,
                'error': 'RELATORIO_INVALIDO',
                'message': friendly_msg
            }
        return {
            'success': False,
            'error': 'ERRO_TECNICO',
            'message': f'Erro no processamento: {error_msg}'
        }

    finally:
        # Limpar arquivo temporário
        if os.path.exists(file_path):
            os.remove(file_path)