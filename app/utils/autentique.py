import os
import requests
import json

AUTENTIQUE_TOKEN = os.getenv('AUTENTIQUE_TOKEN', '').strip()
AUTENTIQUE_SANDBOX = os.getenv('AUTENTIQUE_SANDBOX', 'true').lower() == 'true'

URL = "https://api.autentique.com.br/v2/graphql"

def criar_documento_autentique(nome_signer, email_signer, caminho_pdf):
    query = """
    mutation CreateDocumentMutation(
        $document: DocumentInput!,
        $signers: [SignerInput!]!,
        $file: Upload!,
        $sandbox: Boolean!
    ) {
        createDocument(
            sandbox: $sandbox,
            document: $document,
            signers: $signers,
            file: $file
        ) {
            id
            name
        }
    }
    """

    variables = {
        "document": {
            "name": f"Termo de Adesão - {nome_signer}"
        },
        "signers": [
            {
                "name": nome_signer,
                "email": email_signer,
                "action": "SIGN"
            }
        ],
        "sandbox": AUTENTIQUE_SANDBOX
    }

    operations = json.dumps({
        "query": query,
        "variables": variables
    })

    map_dict = json.dumps({
        "0": ["variables.file"]
    })

    headers = {
        "Authorization": f"Bearer {AUTENTIQUE_TOKEN}"
    }

    with open(caminho_pdf, 'rb') as f:
        files = {
            'operations': (None, operations),
            'map': (None, map_dict),
            '0': ('termo_adesao.pdf', f, 'application/pdf')
        }
        
        response = requests.post(URL, headers=headers, files=files)

    if response.status_code == 200:
        data = response.json()
        if "errors" in data:
            raise Exception(f"{data['errors'][0]['message']}")
        
        doc_id = data.get('data', {}).get('createDocument', {}).get('id')
        return doc_id
    else:
        raise Exception(f"Falha de comunicação HTTP: {response.text}")

def enviar_documento_local_com_link(nome_signer, email_signer, caminho_pdf, nome_documento):
    query = """
    mutation CreateDocumentMutation(
        $document: DocumentInput!,
        $signers: [SignerInput!]!,
        $file: Upload!,
        $sandbox: Boolean!
    ) {
        createDocument(
            sandbox: $sandbox,
            document: $document,
            signers: $signers,
            file: $file
        ) {
            id
            name
            signatures {
                link { short_link }
            }
        }
    }
    """

    variables = {
        "document": {
            "name": nome_documento
        },
        "signers": [
            {
                "name": nome_signer,
                "email": email_signer,
                "action": "SIGN"
            }
        ],
        "sandbox": AUTENTIQUE_SANDBOX
    }

    operations = json.dumps({
        "query": query,
        "variables": variables
    })

    map_dict = json.dumps({
        "0": ["variables.file"]
    })

    headers = {
        "Authorization": f"Bearer {AUTENTIQUE_TOKEN}"
    }

    with open(caminho_pdf, 'rb') as f:
        nome_arq = os.path.basename(caminho_pdf)
        files = {
            'operations': (None, operations),
            'map': (None, map_dict),
            '0': (nome_arq, f, 'application/pdf')
        }
        
        response = requests.post(URL, headers=headers, files=files)

    if response.status_code == 200:
        data = response.json()
        if "errors" in data:
            raise Exception(f"{data['errors'][0]['message']}")
        
        doc = data.get('data', {}).get('createDocument', {})
        doc_id = doc.get('id')
        link = None
        try:
            link = doc.get('signatures', [])[0].get('link', {}).get('short_link')
        except:
            pass
            
        return doc_id, link
    else:
        raise Exception(f"Falha de comunicação HTTP: {response.text}")

def verificar_status_autentique(doc_id):
    query = """
    query CheckStatus($id: UUID!) {
        document(id: $id) {
            signatures {
                signed {
                    created_at
                }
            }
        }
    }
    """
    
    payload = {
        "query": query,
        "variables": {"id": str(doc_id)}
    }
    
    headers = {
        "Authorization": f"Bearer {AUTENTIQUE_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(URL, headers=headers, json=payload)
        if response.status_code == 200:
            data = response.json()
            document_data = data.get('data', {}).get('document')
            if not document_data:
                return False
            signatures = document_data.get('signatures', [])
            for sig in signatures:
                if sig.get('signed'):
                    return True
    except Exception:
        return False
    return False

def obter_link_assinatura_autentique(autentique_document_id):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[Autentique] Buscando link para document_id: {autentique_document_id}")
    
    query = """
    query GetSignerLink($id: UUID!) {
        document(id: $id) {
            signatures {
                link { short_link }
            }
        }
    }
    """
    headers = {
        "Authorization": f"Bearer {AUTENTIQUE_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "query": query,
        "variables": {"id": str(autentique_document_id)}
    }
    try:
        response = requests.post(URL, headers=headers, json=payload, timeout=10)
        logger.info(f"[Autentique] Resposta status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            logger.info(f"[Autentique] Resposta JSON: {json.dumps(data, indent=2)}")
            if "errors" in data:
                logger.error(f"[Autentique] Erro GraphQL: {data['errors']}")
                return None
            
            document = data.get('data', {}).get('document')
            if not document:
                logger.warning("[Autentique] Campo 'document' não encontrado ou é nulo")
                return None
            
            signatures = document.get('signatures')
            if not signatures or not isinstance(signatures, list) or len(signatures) == 0:
                logger.warning("[Autentique] Nenhuma assinatura encontrada ou formato inválido")
                return None
            
            for sig in signatures:
                if sig and isinstance(sig, dict):
                    link_obj = sig.get('link')
                    if link_obj and isinstance(link_obj, dict):
                        short_link = link_obj.get('short_link')
                        if short_link:
                            logger.info(f"[Autentique] Link encontrado: {short_link}")
                            return short_link
            
            logger.warning("[Autentique] Nenhum link válido encontrado nas assinaturas")
            return None
        else:
            logger.error(f"[Autentique] HTTP {response.status_code}: {response.text}")
            return None
    except Exception as e:
        logger.exception(f"[Autentique] Exceção: {e}")
        return None
