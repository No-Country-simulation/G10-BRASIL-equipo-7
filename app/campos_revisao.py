"""Campos de revisão clínica; a conversão para JSON fica interna à aplicação."""
import streamlit as st


def render_campos_revisao(dados, prefixo, disabled=False):
    def texto(rotulo, campo, valor=None):
        return st.text_input(rotulo, value=valor or "", key=f"{prefixo}_{campo}",
                             disabled=disabled).strip() or None

    paciente = dados.get("paciente") or {}
    with st.expander("Paciente", expanded=True):
        nome = texto("Nome do paciente", "paciente_nome", paciente.get("nome"))
        idade = st.number_input("Idade (anos)", min_value=0, value=paciente.get("idade"),
                                step=1, key=prefixo + "_idade", disabled=disabled,
                                placeholder="Não informada")
    medico = dados.get("medico_responsavel") or {}
    with st.expander("Médico responsável", expanded=True):
        nome_medico = texto("Nome do médico", "medico_nome", medico.get("nome"))
        crm = texto("CRM", "crm", medico.get("crm"))
    medicamentos = dados.get("medicamentos") or []
    with st.expander("Medicamentos", expanded=bool(medicamentos)):
        quantidade = st.number_input("Quantidade de medicamentos", min_value=0,
                                     value=len(medicamentos), step=1, disabled=disabled,
                                     key=prefixo + "_quantidade_medicamentos")
        st.caption("Aumente a quantidade para incluir um medicamento; reduza para remover os últimos.")
        corrigidos = []
        for indice in range(quantidade):
            atual = medicamentos[indice] if indice < len(medicamentos) else {}
            st.markdown(f"**Medicamento {indice + 1}**")
            corrigidos.append({
                campo: texto(rotulo, f"medicamento_{indice}_{campo}", atual.get(campo))
                for campo, rotulo in (("nome", "Nome do medicamento"), ("dosagem", "Dosagem"),
                                      ("posologia", "Modo de uso (posologia)"))
            })
    with st.expander("Exame e diagnóstico", expanded=True):
        exame = texto("Exame realizado", "exame", dados.get("exame_realizado"))
        diagnostico = st.text_area("Diagnóstico principal", value=dados.get("diagnostico_principal") or "",
                                   key=prefixo + "_diagnostico", disabled=disabled).strip() or None
        cid = texto("CID", "cid", dados.get("cid_sugerido"))
    return {
        "paciente": {"nome": nome, "idade": idade} if nome is not None or idade is not None else None,
        "medico_responsavel": {"nome": nome_medico, "crm": crm} if nome_medico or crm else None,
        "medicamentos": corrigidos if quantidade else ([] if dados.get("medicamentos") is not None else None),
        "exame_realizado": exame, "diagnostico_principal": diagnostico, "cid_sugerido": cid,
    }
