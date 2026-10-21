"""Regras de triagem (#5). Preencher quando a issue fechar."""

LIMIAR_CONFIANCA = 0.8  # PROVISÓRIO: definir na #5

DESTINOS = {
    "rotina": "processados/rotina",
    "urgencia": "processados/urgencia",
    "ambiguidade": "auditoria-humana/ambiguidade",
}

# Em aberto na #5: urgente + baixa confiança vai para auditoria, alerta ou os dois?
