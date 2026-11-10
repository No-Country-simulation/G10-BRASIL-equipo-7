from agent.adapters import estado_para_resultado


def _estado(rota, destino, score=0.9):
    return {
        "documento": {},
        "score_confianca": score,
        "validacao": {
            "dados_validados": {"dados_extraidos": {"paciente": {"nome": "Maria"}}}
        },
        "decisao_roteamento": {
            "rota": rota,
            "destino_principal": destino,
            "requer_auditoria_humana": rota == "ambiguidade",
            "justificativa_roteamento": "motivo",
            "notificacao_gerada": None,
        },
    }


def test_rotina():
    r = estado_para_resultado(_estado("rotina", "Farmacia_Hospitalar", 0.96), "DOC-1")
    assert r.documento_id == "DOC-1"
    assert r.classificacao == "rotina"
    assert r.destino_principal == "Farmacia_Hospitalar"
    assert r.score_confianca == 0.96
    assert r.alerta_enviado is False
    assert r.dados_extraidos == {"paciente": {"nome": "Maria"}}


def test_urgencia_e_ambiguidade():
    assert estado_para_resultado(_estado("urgencia", "X"), "D").classificacao == "urgencia"
    assert estado_para_resultado(_estado("ambiguidade", "Y", 0.4), "D").classificacao == "ambiguidade"
