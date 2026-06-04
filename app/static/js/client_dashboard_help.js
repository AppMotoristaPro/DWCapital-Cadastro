// Função para abrir o modal de explicação com os dados diários
async function abrirExplicacao(tipo) {
    // tipo pode ser 'bruto', 'liquido', 'lucro'
    const modal = document.getElementById('modal-explicacao');
    const conteudo = document.getElementById('modal-explicacao-conteudo');
    
    // Pega os filtros atuais da URL (os mesmos do dashboard)
    const urlParams = new URLSearchParams(window.location.search);
    const params = {};
    if (urlParams.has('dia')) params.dia = urlParams.get('dia');
    if (urlParams.has('semana_dia')) params.semana_dia = urlParams.get('semana_dia');
    if (urlParams.has('ano')) params.ano = urlParams.get('ano');
    
    conteudo.innerHTML = '<div class="text-center py-8"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-royal mx-auto"></div><p class="mt-4 text-gray-500">Carregando dados...</p></div>';
    modal.classList.remove('hidden');
    
    try {
        const query = new URLSearchParams(params).toString();
        const response = await fetch(`/portal/api/explicacao_dashboard?${query}`);
        const data = await response.json();
        
        let titulo = '';
        let colunas = [];
        let linhaDados = [];
        
        if (tipo === 'bruto') {
            titulo = '📊 Performance Bruta';
            colunas = ['Data', 'Bruto', 'Custos (B3+IRRF1)', 'Líquido do Pregão', 'IRRF 19%', 'Líquido Real'];
            linhaDados = data.dias.map(d => [
                d.data_formatada,
                `R$ ${d.bruto.toFixed(2)}`,
                `R$ ${d.custos_b3_irrf1.toFixed(2)}`,
                `R$ ${d.liquido_pregao.toFixed(2)}`,
                d.liquido_pregao > 0 ? `R$ ${d.irrf_19.toFixed(2)}` : 'Não incide (prejuízo)',
                `R$ ${d.liquido.toFixed(2)}`
            ]);
        } else if (tipo === 'liquido') {
            titulo = '💰 Líquido Operacional';
            colunas = ['Data', 'Líquido do Pregão', 'IRRF 19%', 'Líquido Real'];
            linhaDados = data.dias.map(d => [
                d.data_formatada,
                `R$ ${d.liquido_pregao.toFixed(2)}`,
                d.liquido_pregao > 0 ? `R$ ${d.irrf_19.toFixed(2)}` : 'Não incide (prejuízo)',
                `R$ ${d.liquido.toFixed(2)}`
            ]);
        } else if (tipo === 'lucro') {
            titulo = '🏆 Lucro Limpo (Crédito)';
            const multiplicador = (data.is_isento || data.modelo_negocio === 'compra') ? 1 : 0.7;
            colunas = ['Data', 'Líquido Real', `Repasse DW (${multiplicador === 1 ? '100%' : '30%'})`, 'Seu Crédito'];
            linhaDados = data.dias.map(d => [
                d.data_formatada,
                `R$ ${d.liquido.toFixed(2)}`,
                d.is_comissao ? `R$ ${d.repasse.toFixed(2)}` : 'Licença/Isento',
                multiplicador === 1 ? `R$ ${d.liquido.toFixed(2)}` : `R$ ${(d.liquido * 0.7).toFixed(2)}`
            ]);
        }
        
        // Monta a tabela HTML
        let html = `
            <h3 class="text-xl font-black text-navy mb-4">${titulo}</h3>
            <p class="text-sm text-gray-500 mb-4">Período: <strong>${data.periodo}</strong></p>
            <div class="overflow-x-auto">
                <table class="w-full text-sm border-collapse">
                    <thead class="bg-gray-50 border-b">
                        <tr>
                            ${colunas.map(col => `<th class="px-4 py-2 text-left font-bold text-navy">${col}</th>`).join('')}
                        </tr>
                    </thead>
                    <tbody>
                        ${linhaDados.map(linha => `
                            <tr class="border-b border-gray-100">
                                ${linha.map(cel => `<td class="px-4 py-3">${cel}</td>`).join('')}
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            <div class="mt-6 p-4 bg-blue-50 rounded-xl">
                <div class="flex justify-between items-center">
                    <span class="text-sm font-bold text-navy">Total no período:</span>
                    <span class="text-xl font-black text-royal">
                        ${tipo === 'bruto' ? `R$ ${data.totais.bruto.toFixed(2)}` : 
                          tipo === 'liquido' ? `R$ ${data.totais.liquido.toFixed(2)}` : 
                          `R$ ${data.totais.repasse.toFixed(2)}`}
                    </span>
                </div>
            </div>
            <button onclick="fecharExplicacao()" class="mt-6 w-full py-2 bg-navy text-white rounded-lg text-xs font-black uppercase tracking-widest">Fechar</button>
        `;
        
        conteudo.innerHTML = html;
    } catch (err) {
        console.error('Erro ao carregar dados:', err);
        conteudo.innerHTML = `<div class="text-center py-8 text-red-500">Erro ao carregar dados. Tente novamente mais tarde.</div>`;
    }
}

function fecharExplicacao() {
    document.getElementById('modal-explicacao').classList.add('hidden');
}