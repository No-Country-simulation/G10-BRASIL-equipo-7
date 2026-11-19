import type { DadosFormulario } from '../state/dadosRevisao'
import { Button } from './ui'

export default function CamposRevisao({ dados, onChange }: { dados: DadosFormulario; onChange: (dados: DadosFormulario) => void }) {
  const campo = (chave: 'nome' | 'medico' | 'crm' | 'exame' | 'cid', rotulo: string) => <label className="field">{rotulo}<input value={dados[chave]} onChange={(event) => onChange({ ...dados, [chave]: event.target.value })} placeholder="Não informado" /></label>
  return <div className="clinical-fields">
    <p className="muted small">Confira o original. Deixe em branco as informações ausentes.</p>
    <details open><summary>Paciente</summary><div className="review-fields">
      {campo('nome', 'Nome do paciente')}
      <label className="field">Idade (anos)<input type="number" min={0} step={1} value={dados.idade} placeholder="Não informada" onChange={(event) => onChange({ ...dados, idade: event.target.value })} /></label>
    </div></details>
    <details><summary>Médico responsável</summary><div className="review-fields">{campo('medico', 'Nome do médico')}{campo('crm', 'CRM')}</div></details>
    <details><summary>Medicamentos ({dados.medicamentos.length})</summary><div className="review-fields">
      {dados.medicamentos.map((item, indice) => <fieldset className="medicine-fields" key={indice}><legend>Medicamento {indice + 1}</legend>
        {([['nome', 'Nome do medicamento'], ['dosagem', 'Dosagem'], ['posologia', 'Modo de uso (posologia)']] as const).map(([chave, rotulo]) => <label className="field" key={chave}>{rotulo}<input aria-label={`${rotulo} ${indice + 1}`} value={item[chave]} onChange={(event) => onChange({ ...dados, medicamentos: dados.medicamentos.map((atual, posicao) => posicao === indice ? { ...atual, [chave]: event.target.value } : atual) })} /></label>)}
        <Button onClick={() => onChange({ ...dados, medicamentos: dados.medicamentos.filter((_, posicao) => posicao !== indice) })}>Remover medicamento {indice + 1}</Button>
      </fieldset>)}
      <Button onClick={() => onChange({ ...dados, medicamentosNulos: false, medicamentos: [...dados.medicamentos, { nome: '', dosagem: '', posologia: '' }] })}>Adicionar medicamento</Button>
    </div></details>
    <details><summary>Exame e diagnóstico</summary><div className="review-fields">
      {campo('exame', 'Exame realizado')}
      <label className="field">Diagnóstico principal<textarea rows={3} value={dados.diagnostico} onChange={(event) => onChange({ ...dados, diagnostico: event.target.value })} /></label>
      {campo('cid', 'CID')}
    </div></details>
  </div>
}
