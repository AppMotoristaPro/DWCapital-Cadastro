import os
import requests
import json

AUTENTIQUE_TOKEN = os.getenv('AUTENTIQUE_TOKEN', '').strip()
URL = "https://api.autentique.com.br/v2/graphql"

def criar_documento_autentique(nome_signer, email_signer, caminho_pdf):
    query = """
    mutation CreateDocumentMutation(
        $document: DocumentInput!,
        $signers: [SignerInput!]!,
        $file: Upload!
    ) {
        createDocument(
            sandbox: true,
            document: $document,
            signers: $signers,
            file: $file
        ) {
            id
            name
        }
    }
    """

    # Omitimos o delivery_method, forçando a Autentique a fazer o envio padrão (e-mail)
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
        ]
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
        
        # Apenas pegamos o ID do documento, sem depender de links
        doc_id = data.get('data', {}).get('createDocument', {}).get('id')
        if not doc_id:
            raise Exception("Falha ao registrar o ID do documento.")
            
        return doc_id
    else:
        raise Exception(f"Falha de comunicação HTTP: {response.text}")


def verificar_status_autentique(doc_id):
    query = """
    query CheckStatus($id: ID!) {
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
        "variables": {"id": doc_id}
    }
    
    headers = {
        "Authorization": f"Bearer {AUTENTIQUE_TOKEN}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(URL, headers=headers, json=payload)
    if response.status_code == 200:
        data = response.json()
        
        if "errors" in data:
            return False
            
        signatures = data.get('data', {}).get('document', {}).get('signatures', [])
        for sig in signatures:
            if sig.get('signed') and sig['signed'].get('created_at'):
                return True
        return False
        
    return False

