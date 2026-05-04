import os
import re
from docusign_esign import ApiClient, EnvelopesApi, EnvelopeDefinition, TemplateRole, RecipientViewRequest

# Variáveis do Render
DOCUSIGN_CLIENT_ID = os.getenv('DOCUSIGN_CLIENT_ID')
DOCUSIGN_USER_ID = os.getenv('DOCUSIGN_USER_ID')
DOCUSIGN_ACCOUNT_ID = os.getenv('DOCUSIGN_ACCOUNT_ID')
DOCUSIGN_TEMPLATE_ID = os.getenv('DOCUSIGN_TEMPLATE_ID')

def limpar_chave_rsa(key):
    """
    Limpa a chave RSA de aspas, espaços extras e garante que as quebras 
    de linha sejam interpretadas corretamente pelo Python.
    """
    if not key:
        return ""
    # Remove aspas duplas ou simples que podem ter vindo do Render
    key = key.strip().strip('"').strip("'")
    # Se a chave foi colada com \n literais, converte para quebras reais
    key = key.replace('\\n', '\n')
    return key

DOCUSIGN_PRIVATE_KEY = limpar_chave_rsa(os.getenv('DOCUSIGN_PRIVATE_KEY', ''))

BASE_PATH = "https://demo.docusign.net/restapi"
OAUTH_HOST = "account-d.docusign.com"

def get_docusign_client():
    api_client = ApiClient()
    api_client.set_base_path(BASE_PATH)
    api_client.set_oauth_host_name(OAUTH_HOST)
    
    try:
        token_response = api_client.request_jwt_user_token(
            client_id=DOCUSIGN_CLIENT_ID,
            user_id=DOCUSIGN_USER_ID,
            oauth_host_name=OAUTH_HOST,
            private_key_bytes=DOCUSIGN_PRIVATE_KEY.encode('utf-8'),
            expires_in=3600,
            scopes=["signature", "impersonation"]
        )
        api_client.default_headers["Authorization"] = "Bearer " + token_response.access_token
        return api_client
    except Exception as e:
        # Repassa o erro detalhado para o Flash do Flask
        raise Exception(f"Erro na Autenticação JWT: {str(e)}")

def criar_envelope_embedded(signer_name, signer_email, client_user_id):
    api_client = get_docusign_client()
    envelopes_api = EnvelopesApi(api_client)
    
    signer = TemplateRole(
        email=signer_email,
        name=signer_name,
        role_name="Cliente",
        client_user_id=client_user_id
    )
    
    envelope_definition = EnvelopeDefinition(
        status="sent",
        template_id=DOCUSIGN_TEMPLATE_ID,
        template_roles=[signer]
    )
    
    results = envelopes_api.create_envelope(
        account_id=DOCUSIGN_ACCOUNT_ID,
        envelope_definition=envelope_definition
    )
    
    return results.envelope_id

def gerar_url_assinatura(envelope_id, signer_name, signer_email, client_user_id, return_url):
    api_client = get_docusign_client()
    envelopes_api = EnvelopesApi(api_client)
    
    recipient_view_request = RecipientViewRequest(
        authentication_method="None",
        client_user_id=client_user_id,
        recipient_id="1", 
        return_url=return_url,
        user_name=signer_name,
        email=signer_email
    )
    
    results = envelopes_api.create_recipient_view(
        account_id=DOCUSIGN_ACCOUNT_ID,
        envelope_id=envelope_id,
        recipient_view_request=recipient_view_request
    )
    
    return results.url

