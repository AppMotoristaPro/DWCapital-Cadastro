import os
from flask import current_app
from datetime import datetime
import pytz
from app import db
from app.models import User, DocumentoTemplate, DocumentoCliente
from app.utils.autentique import enviar_documento_local_com_link, verificar_status_autentique, criar_documento_autentique

tz_br = pytz.timezone('America/Sao_Paulo')

def disparar_lote(template_id, user_ids):
    """
    Dispara um template específico de contrato para uma lista de clientes.
    Retorna uma tupla contendo: (qtd_enviados, qtd_erros, lista_sem_email, nome_do_template)
    """
    template = DocumentoTemplate.query.get_or_404(template_id)
    caminho_pdf = os.path.join(current_app.root_path, 'static', 'documentos', template.arquivo_local)
    
    if not os.path.exists(caminho_pdf):
        raise FileNotFoundError(f'Erro: O arquivo "{template.arquivo_local}" não foi encontrado na pasta static/documentos/.')

    enviados = 0
    erros = 0
    sem_email = []
    
    for uid in user_ids:
        cliente = User.query.get(uid)
        if cliente:
            if not cliente.email:
                sem_email.append(cliente.nome)
                continue
                
            try:
                nome_doc = f"{template.nome} - {cliente.nome}"
                doc_id, link = enviar_documento_local_com_link(cliente.nome, cliente.email, caminho_pdf, nome_doc)
                
                novo_doc = DocumentoCliente(
                    user_id=cliente.id,
                    template_id=template.id,
                    autentique_document_id=doc_id,
                    link_assinatura=link,
                    status='pendente'
                )
                db.session.add(novo_doc)
                enviados += 1
            except Exception as e:
                print(f"Erro ao disparar para {cliente.nome}: {e}")
                erros += 1
                
    db.session.commit()
    return enviados, erros, sem_email, template.nome

def gerar_termo_adesao(user):
    """Gera o termo de adesão seguro para o primeiro acesso do investidor."""
    caminho_pdf = os.path.join(current_app.root_path, 'static', 'documentos', 'termo_adesao.pdf')
    doc_id = criar_documento_autentique(
        nome_signer=user.nome,
        email_signer=user.email,
        caminho_pdf=caminho_pdf
    )
    user.docusign_envelope_id = doc_id 
    db.session.commit()
    return doc_id

def verificar_status_termo(user):
    """Verifica na API se o termo principal do primeiro acesso foi assinado."""
    doc_id = user.docusign_envelope_id
    if not doc_id:
        return False
    
    if verificar_status_autentique(doc_id):
        user.termo_assinado = True
        db.session.commit()
        return True
    return False

def verificar_status_documento_cliente(doc_id, user_id):
    """Verifica e atualiza o status de um documento extra no cofre do cliente. Contém escudo IDOR."""
    doc = DocumentoCliente.query.get_or_404(doc_id)
    
    # Escudo IDOR: O cliente não pode checar/atualizar documentos de terceiros
    if doc.user_id != user_id:
        return False, False # (autorizado, assinado)
    
    # Se já foi carimbado no nosso banco, evita gastar requisição na API
    if doc.status == 'assinado':
        return True, True
        
    try:
        if verificar_status_autentique(doc.autentique_document_id):
            doc.status = 'assinado'
            doc.data_assinatura = datetime.now(tz_br)
            db.session.commit()
            return True, True
    except:
        pass
        
    return True, False

