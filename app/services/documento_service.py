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
    FASE 3: Enfileira um template específico de contrato para uma lista de clientes.
    Não chama a API do Autentique aqui, apenas cria a pendência (Just-in-Time).
    """
    template = DocumentoTemplate.query.get_or_404(template_id)
    caminho_pdf = os.path.join(current_app.root_path, 'static', 'documentos', template.arquivo_local)
    
    if not os.path.exists(caminho_pdf):
        raise FileNotFoundError(f'Erro: O arquivo "{template.arquivo_local}" não foi encontrado na pasta static/documentos/.')

    enviados = 0
    erros = 0
    sem_email = []
    
    novos_docs = []
    for uid in user_ids:
        cliente = User.query.get(uid)
        if cliente:
            if not cliente.email:
                sem_email.append(cliente.nome)
                continue
                
            try:
                # Cria a pendência e coloca na fila do usuário
                novo_doc = DocumentoCliente(
                    user_id=cliente.id,
                    template_id=template.id,
                    autentique_document_id=None,
                    link_assinatura=None,
                    status='na_fila'
                )
                novos_docs.append(novo_doc)
                enviados += 1
            except Exception as e:
                print(f"Erro ao enfileirar para {cliente.nome}: {e}")
                erros += 1
                
    if novos_docs:
        db.session.add_all(novos_docs)
        db.session.commit()
        
    return enviados, erros, sem_email, template.nome

def disparar_unico(template_id, user_id):
    """
    FASE 3: Enfileira um template específico para UM único cliente via AJAX.
    """
    template = DocumentoTemplate.query.get(template_id)
    if not template:
        return {"success": False, "message": "Modelo não encontrado no banco de dados."}
        
    caminho_pdf = os.path.join(current_app.root_path, 'static', 'documentos', template.arquivo_local)
    
    if not os.path.exists(caminho_pdf):
        return {"success": False, "message": f"Arquivo físico PDF não encontrado no servidor."}

    cliente = User.query.get(user_id)
    if not cliente:
        return {"success": False, "message": "Cliente não localizado."}
        
    if not cliente.email:
        return {"success": False, "message": "Cliente não possui e-mail cadastrado."}
        
    try:
        # Cria a pendência e coloca na fila do usuário
        novo_doc = DocumentoCliente(
            user_id=cliente.id,
            template_id=template.id,
            autentique_document_id=None,
            link_assinatura=None,
            status='na_fila'
        )
        db.session.add(novo_doc)
        db.session.commit()
        
        return {
            "success": True, 
            "message": "Enfileirado com sucesso para disparo futuro.", 
            "nome_template": template.nome
        }
    except Exception as e:
        db.session.rollback()
        return {"success": False, "message": str(e)}

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
    
    if doc.user_id != user_id:
        return False, False 
    
    if doc.status == 'assinado':
        return True, True
        
    try:
        # Garante que só verifica se ele tem ID na autentique
        if doc.autentique_document_id and verificar_status_autentique(doc.autentique_document_id):
            doc.status = 'assinado'
            doc.data_assinatura = datetime.now(tz_br)
            db.session.commit()
            return True, True
    except:
        pass
        
    return True, False

