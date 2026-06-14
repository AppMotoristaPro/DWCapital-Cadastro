// Obtém o token CSRF da meta tag
function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

function toggleDetalhes(clienteId) {
    const detalhesRow = document.getElementById(`detalhes-${clienteId}`);
    if (detalhesRow) detalhesRow.classList.toggle('hidden');
}

async function marcarParcelaPaga(parcelaId, clienteId) {
    if (!confirm('Deseja marcar esta parcela como PAGA?')) return;
    
    const token = getCSRFToken();
    if (!token) {
        alert('Token CSRF não encontrado. Recarregue a página.');
        return;
    }
    
    try {
        const response = await fetch(`/admin/parcela/pagar/${parcelaId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': token
            },
            credentials: 'same-origin'
        });
        
        let data;
        try {
            data = await response.json();
        } catch (e) {
            alert('Erro inesperado do servidor. Verifique os logs.');
            return;
        }
        
        if (response.ok && data.success) {
            window.location.reload();
        } else {
            alert(data.message || 'Erro ao marcar parcela como paga.');
        }
    } catch (error) {
        console.error('Erro:', error);
        alert('Erro de comunicação com o servidor.');
    }
}