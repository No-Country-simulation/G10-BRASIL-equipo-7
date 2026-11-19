import { Button } from './ui'

export default function RevisaoForm() {
  return <form onSubmit={(event) => event.preventDefault()}>
    <p className="muted small">O encaminhamento pelo React será conectado na próxima etapa. Por enquanto, use a revisão no Streamlit.</p>
    <fieldset disabled className="review-fields">
      <legend className="sr-only">Dados da revisão humana</legend>
      <label className="field">Nome do paciente<input placeholder="Não informado" /></label>
      <label className="field">Idade (anos)<input type="number" min={0} placeholder="Não informada" /></label>
      <label className="field">Médico responsável<input placeholder="Não informado" /></label>
      <label className="field">CRM<input placeholder="Não informado" /></label>
      <details><summary>Medicamentos, exame e diagnóstico</summary><div className="review-fields">
        <label className="field">Medicamento<input placeholder="Não informado" /></label>
        <label className="field">Dosagem<input placeholder="Não informada" /></label>
        <label className="field">Modo de uso<input placeholder="Não informado" /></label>
        <label className="field">Exame realizado<input placeholder="Não informado" /></label>
        <label className="field">Diagnóstico principal<textarea rows={2} placeholder="Não informado" /></label>
        <label className="field">CID<input placeholder="Não informado" /></label>
      </div></details>
      <fieldset><legend>Destino</legend><div className="actions"><label><input type="radio" name="destino" value="rotina" defaultChecked /> Rotina</label><label><input type="radio" name="destino" value="urgencia" /> Urgência</label></div></fieldset>
      <label className="field">Departamento<select defaultValue=""><option value="">Selecione o departamento</option></select></label>
      <label className="field">Revisor<input placeholder="Nome do revisor" /></label>
      <label className="field">Observação (opcional)<textarea rows={2} placeholder="Acrescente uma observação, se necessário." /></label>
      <Button variant="primary" className="full-width" type="submit">Confirmar encaminhamento</Button>
    </fieldset>
  </form>
}
