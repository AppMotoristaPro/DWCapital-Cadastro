import os
import zipfile
from datetime import datetime

def criar_backup():
    # Caminho da pasta de downloads (ajustado para o Termux após termux-setup-storage)
    pasta_origem = os.getcwd()
    pasta_downloads = os.path.expanduser('~/storage/downloads')
    
    # Nome do arquivo com data e hora para não sobrescrever backups antigos
    data_hora = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    nome_zip = f"backup_dw_capital_{data_hora}.zip"
    caminho_final = os.path.join(pasta_downloads, nome_zip)

    # Pastas que NÃO queremos incluir (para deixar o backup leve e seguro)
    ignorados = {'.git', '.venv', '__pycache__', 'venv', 'node_modules'}

    print(f"Iniciando backup de: {pasta_origem}")
    print(f"Salvando em: {caminho_final}")

    with zipfile.ZipFile(caminho_final, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for raiz, pastas, arquivos in os.walk(pasta_origem):
            # Remove pastas ignoradas do processo de busca
            pastas[:] = [p for p in pastas if p not in ignorados]
            
            for arquivo in arquivos:
                # Pula arquivos de backup anteriores para não criar um zip dentro de outro
                if arquivo.endswith('.zip'):
                    continue
                    
                caminho_completo = os.path.join(raiz, arquivo)
                caminho_relativo = os.path.relpath(caminho_completo, pasta_origem)
                
                zipf.write(caminho_completo, caminho_relativo)
                print(f"Adicionado: {caminho_relativo}")

    print("-" * 30)
    print("Backup concluído com sucesso!")
    print(f"Arquivo disponível em: {caminho_final}")

if __name__ == "__main__":
    criar_backup()

