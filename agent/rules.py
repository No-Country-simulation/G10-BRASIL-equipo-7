"""Destinos da triagem e limiar carregado da configuração na inicialização."""

from agent.config import carregar_configuracao

LIMIAR_CONFIANCA = carregar_configuracao().limiar_confianca

DESTINOS = {
    "rotina": "processados/rotina",
    "urgencia": "processados/urgencia",
    "ambiguidade": "auditoria-humana/ambiguidade",
}
