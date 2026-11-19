import type { ResultadoTriagem } from '../api/contratos'
import { rotulos } from '../api/contratos'
import HistoricoRevisao from './HistoricoRevisao'

function formatar(valor: unknown): string {
  if (valor === null || valor === undefined || valor === '') return 'Não informado'
  if (Array.isArray(valor)) return valor.length ? valor.map(formatar).join(' · ') : 'Não informado'
  if (typeof valor === 'object') return Object.entries(valor).map(([campo, item]) => `${campo.replaceAll('_', ' ')}: ${formatar(item)}`).join(' · ')
  return String(valor)
}
export default function ResumoTriagem({ resultado, justificativaOriginal, decisao }: {
  resultado: ResultadoTriagem; justificativaOriginal?: string | null; decisao?: Record<string, unknown> | null
}) {
  return <div className="triage-result">
    <span className={`route-badge badge-${resultado.classificacao}`}>{rotulos[resultado.classificacao]}</span>
    <p className="muted small">Documento: {resultado.documento_id}</p>
    <p><strong>Encaminhado para</strong><br />{resultado.destino_principal}</p>
    <p><strong>Confiança da análise</strong><br />{resultado.score_confianca.toLocaleString('pt-BR', { style: 'percent', maximumFractionDigits: 1 })}</p>
    <p>{justificativaOriginal ?? resultado.justificativa}</p>
    {resultado.classificacao === 'urgencia' && <p className="muted small">{resultado.alerta_enviado ? 'Alerta confirmado pelo webhook.' : 'Alerta sem confirmação de envio.'}</p>}
    {decisao && <HistoricoRevisao decisao={decisao} />}
    <dl>{Object.entries(resultado.dados_extraidos).map(([campo, valor]) => <div key={campo}><dt>{campo === 'medico_responsavel' ? 'Médico responsável' : campo.replaceAll('_', ' ')}</dt><dd>{formatar(valor)}</dd></div>)}</dl>
  </div>
}
