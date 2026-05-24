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

# NOVA FUNÇÃO SIMPLES: monta a URL de visualização usando o autentique_document_id
def obter_url_visualizacao_autentique(autentique_document_id):
    """
    Retorna a URL pública do documento no painel da Autentique.
    Exemplo: https://painel.autentique.com.br/documentos/f4f9b303-80e6-d20c-946a-00943a204048
    """
    return f"https://painel.autentique.com.br/documentos/{autentique_document_id}"
