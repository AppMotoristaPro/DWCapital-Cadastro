import os
import shutil

# Configurações de diretório
DIR_ORIGEM = "./app/templates"
# Usa o caminho padrão do Termux para a pasta Downloads
DIR_DESTINO = os.path.expanduser("~/storage/downloads/dwcapital_htmls")

def exportar_htmls():
    print("Iniciando extração segura dos arquivos HTML...")
    
    # Cria a pasta de destino se ela não existir
    if not os.path.exists(DIR_DESTINO):
        os.makedirs(DIR_DESTINO)
        print(f"📁 Pasta criada: {DIR_DESTINO}")

    contador = 0
    
    # Varre todas as pastas e subpastas de templates
    for raiz, pastas, arquivos in os.walk(DIR_ORIGEM):
        for arquivo in arquivos:
            if arquivo.endswith(".html"):
                caminho_origem = os.path.join(raiz, arquivo)
                
                # Descobre o caminho relativo (ex: admin/index.html)
                caminho_relativo = os.path.relpath(caminho_origem, DIR_ORIGEM)
                
                # Substitui as barras por underline para criar um nome único (ex: admin_index.html)
                nome_unico = caminho_relativo.replace(os.sep, "_")
                
                caminho_destino = os.path.join(DIR_DESTINO, nome_unico)
                
                # Copia o arquivo mantendo as propriedades originais
                shutil.copy2(caminho_origem, caminho_destino)
                print(f"✅ Copiado: {caminho_relativo} -> {nome_unico}")
                contador += 1

    print(f"\n🚀 Sucesso absoluto! {contador} arquivos HTML copiados para: {DIR_DESTINO}")

if __name__ == "__main__":
    exportar_htmls()

