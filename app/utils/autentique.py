import os
import requests
import json

# Pega o token do Render e limpa espaços invisíveis
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
            signatures {
                link {
                    short_link
                }
            }
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
                "action": "SIGN",
                # CORREÇÃO: O termo exato exigido pela API para gerar apenas o link
                "delivery_method": "DELIVERY_METHOD_LINK" 
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

    # Envio do arquivo PDF junto com as variáveis GraphQL
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
        
        # Extração "Crash-Proof" usando .get() para não quebrar a tela
        create_doc = data.get('data', {}).get('createDocument', {})
        doc_id = create_doc.get('id')
        
        link_assinatura = None
        signatures = create_doc.get('signatures', [])
        
        if signatures:
            sig = signatures[0]
            link_obj = sig.get('link')
            if link_obj:
                link_assinatura = link_obj.get('short_link')
                
        if not link_assinatura:
            raise Exception("O documento foi gerado, mas a Autentique não liberou o link direto.")
        
        return doc_id, link_assinatura
    else:
        raise Exception(f"Falha de comunicação HTTP: {response.text}")


def verificar_status_autentique(doc_id):
    """
    Verifica na API da Autentique se o documento já possui data de assinatura.
    """
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
            print(f"Erro na verificação Autentique: {data['errors']}")
            return False
            
        signatures = data.get('data', {}).get('document', {}).get('signatures', [])
        for sig in signatures:
            if sig.get('signed') and sig['signed'].get('created_at'):
                return True
        return False
        
    return False

