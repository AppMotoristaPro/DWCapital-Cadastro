import os

# Configurações
DIRETORIO_RAIZ = "."
ARQUIVO_SAIDA = os.path.expanduser("~/storage/downloads/raiox_projeto_python.txt")

# O que NÃO queremos ler (para não travar o script nem gerar lixo)
PASTAS_IGNORADAS = {'.git', '__pycache__', 'venv', '.venv', 'node_modules', 'instance'}
EXTENSOES_PERMITIDAS = {'.py', '.html', '.css', '.js', '.txt', '.md', '.env.example'}

def gerar_arvore(caminho, prefixo=""):
    """Gera a representação visual da estrutura de pastas (Tree)."""
    arvore_str = ""
    try:
        itens = sorted(os.listdir(caminho))
    except PermissionError:
        return ""

    # Filtra as pastas ignoradas e arquivos ocultos/indesejados
    itens_filtrados = [
        i for i in itens 
        if i not in PASTAS_IGNORADAS 
        and not i.endswith('.sqlite3') 
        and not i.endswith('.pdf')
        and not i.endswith('.pyc')
    ]

    for i, item in enumerate(itens_filtrados):
        caminho_completo = os.path.join(caminho, item)
        eh_ultimo = (i == len(itens_filtrados) - 1)
        marcador = "└── " if eh_ultimo else "├── "
        
        arvore_str += f"{prefixo}{marcador}{item}\n"
        
        if os.path.isdir(caminho_completo):
            extensao_prefixo = "    " if eh_ultimo else "│   "
            arvore_str += gerar_arvore(caminho_completo, prefixo + extensao_prefixo)
            
    return arvore_str

def compilar_projeto():
    """Gera o arquivo final com a árvore e os códigos."""
    print("🔍 Iniciando varredura profunda do projeto...")
    
    with open(ARQUIVO_SAIDA, 'w', encoding='utf-8') as f_saida:
        # 1. Escreve a Árvore do Projeto
        f_saida.write("=" * 50 + "\n")
        f_saida.write("1. ESTRUTURA DE PASTAS (TREE)\n")
        f_saida.write("=" * 50 + "\n\n")
        f_saida.write(".\n")
        f_saida.write(gerar_arvore(DIRETORIO_RAIZ))
        f_saida.write("\n\n")
        
        # 2. Escreve o Conteúdo dos Arquivos
        f_saida.write("=" * 50 + "\n")
        f_saida.write("2. CÓDIGO FONTE DOS ARQUIVOS\n")
        f_saida.write("=" * 50 + "\n\n")
        
        for raiz, pastas, arquivos in os.walk(DIRETORIO_RAIZ):
            # Modifica a lista de pastas "in-place" para o os.walk ignorá-las
            pastas[:] = [p for p in pastas if p not in PASTAS_IGNORADAS]
            
            for arquivo in sorted(arquivos):
                caminho_completo = os.path.join(raiz, arquivo)
                _, extensao = os.path.splitext(arquivo)
                
                # Lê apenas se for uma extensão permitida ou se for o requirements.txt
                if extensao in EXTENSOES_PERMITIDAS or arquivo == 'requirements.txt':
                    f_saida.write(f"\n{'=' * 50}\n")
                    f_saida.write(f"ARQUIVO: {caminho_completo}\n")
                    f_saida.write(f"{'=' * 50}\n")
                    
                    try:
                        with open(caminho_completo, 'r', encoding='utf-8') as f_entrada:
                            f_saida.write(f_entrada.read() + "\n")
                    except Exception as e:
                        f_saida.write(f"[⚠️ Erro ao tentar ler arquivo: {e}]\n")

    print(f"✅ Sucesso absoluto! O arquivo foi salvo em: {ARQUIVO_SAIDA}")

if __name__ == "__main__":
    compilar_projeto()

