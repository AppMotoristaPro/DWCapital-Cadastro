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
    Retorna objeto date ou None. (usado apenas para auditoria, não para validação)
    """
    soup = BeautifulSoup(conteudo, 'html.parser')
    for linha in soup.find_all('tr'):
        ths = linha.find_all('th')
        if len(ths) >= 2 and 'Data:' in ths[0].get_text():
            data_str = ths[1].get_text(strip=True)
            # Formato esperado: "2026.06.08 12:21"
            match = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', data_str)
            if match:
                ano, mes, dia = map(int, match.groups())
                return datetime(ano, mes, dia).date()
    return None


def verificar_operacoes_no_html(conteudo, data_alvo):
    """
    Verifica se há operações (trades) na data_alvo dentro do HTML.
    Considera apenas operações JÁ FECHADAS (tabela "Posições") e transações (exceto balance).
    NÃO considera "Posições Abertas".
    Retorna (teve_operacao, lista_de_operacoes_encontradas)
    """
    soup = BeautifulSoup(conteudo, 'html.parser')
    data_str = data_alvo.strftime('%Y.%m.%d')
    operacoes = []

    # ---- Tabela de Posições (operações fechadas) ----
    for table in soup.find_all('table', {'cellspacing': '1', 'cellpadding': '3'}):
        for row in table.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 13:
                horario = cells[0].get_text(strip=True)
                if horario.startswith(data_str):
                    # Qualquer linha com data correspondente indica operação
                    operacoes.append(('Posições', horario, cells[12].get_text(strip=True)))

    # ---- Tabela de Transações (ignorar 'balance') ----
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
                            if tipo != 'balance':
                                operacoes.append(('Transações', horario, cells[11].get_text(strip=True)))

    # Não verificamos "Posições Abertas" pois não indicam operação no dia específico
    # (a data de abertura pode ser de dias anteriores)

    return len(operacoes) > 0, operacoes