// Alterna a exibição dos detalhes das parcelas (expandir/colapsar)
function toggleDetalhes(clienteId) {
    const detalhesRow = document.getElementById(`detalhes-${clienteId}`);
    if (detalhesRow) {
        detalhesRow.classList.toggle('hidden');
    }
}

// Marcar uma parcela como paga via AJAX
async function marcarParcelaPaga(parcelaId, clienteId) {
    if (!confirm('Deseja marcar esta parcela como PAGA?')) {
        return;
    }
    
    const token = document.querySelector('input[name="csrf_token"]')?.value || '';
    
    try {
        const response = await fetch(`/admin/parcela/pagar/${parcelaId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': token
            }
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Recarrega a página para atualizar todos os dados (simples e seguro)
            window.location.reload();
        } else {
            alert(data.message || 'Erro ao marcar parcela como paga.');
        }
    } catch (error) {
        console.error('Erro:', error);
        alert('Erro de comunicação com o servidor.');
    }
}