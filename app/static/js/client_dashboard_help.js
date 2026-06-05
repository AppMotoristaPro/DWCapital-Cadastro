// Função principal que gera o texto explicativo (estilo balão de diálogo)
async function abrirExplicacao(tipo) {
    const modal = document.getElementById('modal-explicacao');
    const conteudo = document.getElementById('modal-explicacao-conteudo');
    
    const urlParams = new URLSearchParams(window.location.search);
    const params = {};
    if (urlParams.has('dia')) params.dia = urlParams.get('dia');
    if (urlParams.has('semana_dia')) params.semana_dia = urlParams.get('semana_dia');
    if (urlParams.has('ano')) params.ano = urlParams.get('ano');
    
    conteudo.innerHTML = '<div class="text-center py-8"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-royal mx-auto"></div><p class="mt-4 text-gray-500">Carregando explicação...</p></div>';
    modal.classList.remove('hidden');
    
    try {
        const query = new URLSearchParams(params).toString();
        const response = await fetch(`/portal/api/explicacao_dashboard?${query}`);
        const data = await response.json();
        
        const totalBruto = data.totais.bruto;
        const totalLiquido = data.totais.liquido;
        const isComissao = (data.modelo_negocio !== 'compra' && !data.is_isento);
        const multiplicador = isComissao ? 0.7 : 1.0;
        const percentualTexto = (multiplicador === 1) ? '100%' : '70%';
        const lucroCliente = totalLiquido * multiplicador;
        
        let html = '';
        
        if (tipo === 'bruto') {
            html = `
                <div class="flex items-start gap-4">
                    <div class="w-16 h-16 bg-royal/10 rounded-full flex items-center justify-center text-3xl">🤖</div>
                    <div class="flex-1 bg-yellow-50 border-2 border-yellow-200 rounded-2xl p-6 shadow-md relative">
                        <div class="absolute -left-3 top-5 w-4 h-4 bg-yellow-50 border-l-2 border-b-2 border-yellow-200 transform rotate-45"></div>
                        <p class="text-sm text-gray-700 leading-relaxed">
                            <strong class="text-royal">Olá! Vou te explicar como chegamos na Performance Bruta.</strong><br><br>
                            A <strong>Performance Bruta</strong> é a soma de todos os <strong class="text-navy">“Líquidos do Pregão”</strong> de cada dia que você enviou a nota de corretagem.<br>
                            O Líquido do Pregão é o valor após os custos da B3 e o IRRF de 1%.<br><br>
                            No período selecionado, você enviou notas em <strong>${data.dias.length} dias</strong>.<br>
                            Somando todos eles, chegamos a:<br>
                            <span class="text-2xl font-black text-green-600 block text-center my-3">R$ ${totalBruto.toFixed(2)}</span>
                            <span class="text-[10px] text-gray-500 block text-center">Este é o valor bruto que aparece no card.</span><br>
                            <span class="text-xs text-gray-600">💡 <strong>Atenção:</strong> aqui <strong>ainda não foi descontado o IRRF de 19%</strong> sobre os lucros. Esse desconto aparece no próximo card (Líquido Operacional).</span>
                        </p>
                    </div>
                </div>
            `;
        } 
        else if (tipo === 'liquido') {
            html = `
                <div class="flex items-start gap-4">
                    <div class="w-16 h-16 bg-royal/10 rounded-full flex items-center justify-center text-3xl">💰</div>
                    <div class="flex-1 bg-yellow-50 border-2 border-yellow-200 rounded-2xl p-6 shadow-md relative">
                        <div class="absolute -left-3 top-5 w-4 h-4 bg-yellow-50 border-l-2 border-b-2 border-yellow-200 transform rotate-45"></div>
                        <p class="text-sm text-gray-700 leading-relaxed">
                            <strong class="text-royal">Aqui está o valor que efetivamente caiu na sua conta (antes do repasse).</strong><br><br>
                            Para cada dia, pegamos o <strong>Líquido do Pregão</strong> e aplicamos a regra do IRRF 19%:<br>
                            • <strong>Se o dia teve lucro</strong> (Líquido do Pregão > 0), subtraímos 19% de imposto.<br>
                            • <strong>Se o dia teve prejuízo</strong> (Líquido do Pregão ≤ 0), <strong>não pagamos IRRF</strong> (apenas carregamos o prejuízo).<br><br>
                            Somando todos os dias, chegamos ao <strong>Líquido Operacional</strong>:<br>
                            <span class="text-2xl font-black text-green-600 block text-center my-3">R$ ${totalLiquido.toFixed(2)}</span>
                            <span class="text-[10px] text-gray-500 block text-center">Este é o valor líquido após IRRF.</span><br>
                            <span class="text-xs text-gray-600">📌 Exemplo: se um dia você teve R$ 1.000 de lucro, o IRRF foi R$ 190, sobrando R$ 810. Se teve prejuízo de R$ 500, ficou -R$ 500.</span>
                        </p>
                    </div>
                </div>
            `;
        } 
        else if (tipo === 'lucro') {
            const mensagemFinal = (multiplicador === 1) 
                ? 'Você fica com <strong>100%</strong> do Líquido Operacional.' 
                : 'Você recebe <strong>70%</strong> do Líquido Operacional (a DW Capital fica com 30%).';
            html = `
                <div class="flex items-start gap-4">
                    <div class="w-16 h-16 bg-royal/10 rounded-full flex items-center justify-center text-3xl">🏆</div>
                    <div class="flex-1 bg-yellow-50 border-2 border-yellow-200 rounded-2xl p-6 shadow-md relative">
                        <div class="absolute -left-3 top-5 w-4 h-4 bg-yellow-50 border-l-2 border-b-2 border-yellow-200 transform rotate-45"></div>
                        <p class="text-sm text-gray-700 leading-relaxed">
                            <strong class="text-royal">Este é o valor que você efetivamente recebe (seu lucro total).</strong><br><br>
                            Aplicamos a regra de repasse:<br>
                            • ${mensagemFinal}<br>
                            No seu caso:<br>
                            <strong class="text-navy">Líquido Operacional = R$ ${totalLiquido.toFixed(2)}</strong><br>
                            <strong class="text-navy">Seu percentual = ${percentualTexto}</strong><br>
                            <span class="text-xl font-black text-green-600 block text-center my-3">R$ ${lucroCliente.toFixed(2)}</span>
                            <span class="text-[10px] text-gray-500 block text-center">Este é o valor que vai para a sua conta.</span><br>
                            <span class="text-xs text-gray-600">📌 Dica: Se você tiver dúvidas sobre os valores diários, clique no link abaixo.</span>
                        </p>
                    </div>
                </div>
                <div class="text-center mt-4">
                    <button onclick="abrirDetalhamentoDiario()" class="text-[10px] text-royal underline">Ver detalhamento por dia</button>
                </div>
            `;
        }
        
        html += `
            <div class="mt-6 flex justify-end">
                <button onclick="fecharExplicacao()" class="px-4 py-2 bg-navy text-white rounded-lg text-xs font-black uppercase tracking-widest">Fechar</button>
            </div>
        `;
        
        window.dadosExplicacao = data;
        conteudo.innerHTML = html;
    } catch (err) {
        console.error('Erro ao carregar dados:', err);
        conteudo.innerHTML = `<div class="text-center py-8 text-red-500">Erro ao carregar dados. Tente novamente mais tarde.</div>`;
    }
}

function fecharExplicacao() {
    document.getElementById('modal-explicacao').classList.add('hidden');
}

function abrirDetalhamentoDiario() {
    if (!window.dadosExplicacao) return;
    const data = window.dadosExplicacao;
    let titulo = '📊 Detalhamento por dia';
    let colunas = ['Data', 'Líquido do Pregão', 'IRRF 19%', 'Líquido Real'];
    let linhaDados = data.dias.map(d => [
        d.data_formatada,
        `R$ ${d.liquido_pregao.toFixed(2)}`,
        d.liquido_pregao > 0 ? `R$ ${d.irrf_19.toFixed(2)}` : 'Não incide',
        `R$ ${d.liquido.toFixed(2)}`
    ]);
    
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
                <span class="text-sm font-bold text-navy">Total Líquido do período:</span>
                <span class="text-xl font-black text-royal">R$ ${data.totais.liquido.toFixed(2)}</span>
            </div>
        </div>
        <button onclick="fecharExplicacao()" class="mt-6 w-full py-2 bg-navy text-white rounded-lg text-xs font-black uppercase tracking-widest">Fechar</button>
    `;
    
    const conteudo = document.getElementById('modal-explicacao-conteudo');
    conteudo.innerHTML = html;
}