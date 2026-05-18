import os
import requests
import json

class PixService:
    @staticmethod
    def _obter_caminho_raiz():
        """Retorna o caminho absoluto da raiz do projeto de forma blindada"""
        # __file__ mapeia: app/services/pix_service.py
        # 1º dirname vai para: app/services
        # 2º dirname vai para: app
        # 3º dirname vai para a raiz: /opt/render/project/src
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    @staticmethod
    def _obter_token():
        """Efetua a autenticação OAuth2 de duas vias (MTLS) com o Banco Inter"""
        client_id = os.getenv('INTER_CLIENT_ID')
        client_secret = os.getenv('INTER_CLIENT_SECRET')
        
        # AJUSTE: Agora busca os arquivos diretamente na raiz do projeto, como o Render exige
        base_dir = PixService._obter_caminho_raiz()
        cert_path = os.path.join(base_dir, 'inter.crt')
        key_path = os.path.join(base_dir, 'inter.key')
        
        if not os.path.exists(cert_path) or not os.path.exists(key_path):
            raise FileNotFoundError("Chaves de certificado inter.crt ou inter.key não localizadas na raiz do projeto.")
            
        url = "https://cdpj.sandbox.bancointer.com.br/oauth/v2/token"
        payload = {
            'grant_type': 'client_credentials',
            'scope': 'cob.write cob.read webhook.write webhook.read'
        }
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        response = requests.post(
            url, 
            data=payload, 
            headers=headers, 
            auth=(client_id, client_secret), 
            cert=(cert_path, key_path)
        )
        
        if response.status_code == 200:
            return response.json().get('access_token')
        else:
            raise Exception(f"Erro ao obter token do Banco Inter: {response.text}")

    @staticmethod
    def criar_cobranca_imediata(valor, nome_devedor, cpf_devedor):
        """Dispara uma ordem de cobrança para o banco gerar o txid e a string copia e cola"""
        token = PixService._obter_token()
        
        # AJUSTE: Rota de leitura direto da raiz sincronizada para a cobranca
        base_dir = PixService._obter_caminho_raiz()
        cert_path = os.path.join(base_dir, 'inter.crt')
        key_path = os.path.join(base_dir, 'inter.key')
        
        url = "https://cdpj.sandbox.bancointer.com.br/pix/v2/cob"
        chave_pix = os.getenv('INTER_CHAVE_PIX', 'suachave@dwcapital.com.br')
        
        payload = {
            "calendario": {
                "expiracao": 3600
            },
            "devedor": {
                "cpf": ''.join(filter(str.isdigit, str(cpf_devedor))),
                "nome": nome_devedor
            },
            "valor": {
                "original": f"{valor:.2f}"
            },
            "chave": chave_pix
        }
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        response = requests.post(url, json=payload, headers=headers, cert=(cert_path, key_path))
        
        if response.status_code in [200, 201]:
            res_data = response.json()
            return {
                "txid": res_data.get("txid"),
                "pix_copia_e_cola": res_data.get("pixCopiaECola")
            }
        else:
            raise Exception(f"Erro ao criar cobrança no Banco Inter: {response.text}")