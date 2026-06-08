"""
Serviço para validação de relatórios HTML do MetaTrader 5
Utilizado na funcionalidade "Não operei nesse dia"
"""

import re
from bs4 import BeautifulSoup
from datetime import datetime


def validar_estrutura_html_mt5(conteudo):
    """
    Verifica se o conteúdo HTML corresponde ao padrão de relatório do MetaTrader 5.
    Retorna (bool, mensagem_erro)
    """
    soup = BeautifulSoup(conteudo, 'html.parser')
    
    # 1. Meta tag generator
    generator = soup.find('meta', {'name': 'generator'})
    if not generator or generator.get('content') != 'client terminal':
        return False, "Arquivo não é um relatório válido do MetaTrader (meta tag 'generator' ausente ou incorreta)."
    
    # 2. Título da página
    title = soup.find('title')
    if not title or 'Relatório do Histórico de Negociação' not in title.text:
        return False, "Título não corresponde ao padrão do MetaTrader."
    
    # 3. Seções obrigatórias
    secoes_esperadas = ['Posições', 'Ordens', 'Transações']
    for secao in secoes_esperadas:
        if not soup.find('th', string=re.compile(secao)):
            return False, f"Seção '{secao}' não encontrada no relatório."
    
    return True, ""


def extrair_data_do_html(conteudo):
    """
    Extrai a data do relatório a partir da linha "Data:" no HTML.
    Retorna objeto date ou None.
    """
    soup = BeautifulSoup(conteudo, 'html.parser')
    for linha in soup.find_all('tr'):
        ths = linha.find_all('th')
        if len(ths) >= 2 and 'Data:' in ths[0].get_text():
            data_str = ths[1].get_text(strip=True)
            # Formato esperado: "2026.06.07 17:41"
            match = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', data_str)
            if match:
                ano, mes, dia = map(int, match.groups())
                return datetime(ano, mes, dia).date()
    return None


def verificar_operacoes_no_html(conteudo, data_alvo):
    """
    Verifica se há operações (trades) na data_alvo dentro do HTML.
    Retorna (teve_operacao, lista_de_operacoes_encontradas)
    """
    soup = BeautifulSoup(conteudo, 'html.parser')
    data_str = data_alvo.strftime('%Y.%m.%d')
    operacoes = []

    # ---- Tabela de Posições ----
    # A tabela de posições geralmente tem atributos cellspacing="1" cellpadding="3"
    for table in soup.find_all('table', {'cellspacing': '1', 'cellpadding': '3'}):
        for row in table.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 13:  # Colunas: Horário, Position, Ativo, Tipo, Volume, Preço, S/L, T/P, Horário, Preço, Comissão, Swap, Lucro
                horario = cells[0].get_text(strip=True)
                if horario.startswith(data_str):
                    lucro = cells[12].get_text(strip=True).replace(' ', '')
                    if lucro and lucro not in ('0', '0.00'):
                        operacoes.append(('Posições', horario, lucro))

    # ---- Tabela de Transações ----
    # Localizar tabela que contém cabeçalho "Horário" e "Oferta"
    for table in soup.find_all('table'):
        header_row = table.find('tr', bgcolor='#E5F0FC')
        if header_row:
            ths = header_row.find_all('th')
            if len(ths) >= 2 and 'Horário' in ths[0].get_text() and 'Oferta' in ths[1].get_text():
                for row in table.find_all('tr'):
                    cells = row.find_all('td')
                    if len(cells) >= 13:
                        horario = cells[0].get_text(strip=True)
                        if horario.startswith(data_str):
                            tipo = cells[3].get_text(strip=True).lower()
                            if tipo != 'balance':  # ignorar transações de saldo
                                lucro = cells[11].get_text(strip=True).replace(' ', '')
                                if lucro and lucro not in ('0', '0.00'):
                                    operacoes.append(('Transações', horario, lucro))
    
    return len(operacoes) > 0, operacoes