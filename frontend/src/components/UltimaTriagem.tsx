import { useState } from 'react'
import { rotulos } from '../api/contratos'
import { useSessao } from '../state/sessao'
import Icon from './Icon'
import { Button, EmptyState, Panel } from './ui'

function formatar(valor: unknown): string {
  if (valor === null || valor === undefined || valor === '') return 'Não informado'
  if (Array.isArray(valor)) return valor.length ? valor.map(formatar).join(' · ') : 'Não informado'
  if (typeof valor === 'object') return Object.entries(valor).map(([campo, item]) => `${campo.replaceAll('_', ' ')}: ${formatar(item)}`).join(' · ')
  return String(valor)
}

export default function UltimaTriagem() {
  const { ultima, consultando, trocarContexto } = useSessao()
  const [aberto, setAberto] = useState(false)
  const resultado = ultima?.resultado
  return <Panel title="Última triagem">
    {!ultima || !resultado ? <EmptyState title="Nenhuma triagem nesta sessão">O último documento analisado aparecerá aqui após o envio.</EmptyState> : <>
      <div className="file-summary"><Icon name="file" /><strong>{ultima.nome}</strong><span className={`route-badge badge-${resultado.classificacao}`}>{rotulos[resultado.classificacao]}</span></div>
      <div className="last-triage-actions">
        <Button aria-expanded={aberto} onClick={() => setAberto(!aberto)}><Icon name="file" />Ver resultado</Button>
        <Button disabled={consultando || !ultima.chave} onClick={() => ultima.chave && trocarContexto({ tipo: 'documento', nome: ultima.nome,
          referencia: { categoria: resultado.classificacao, chave: ultima.chave } })}><Icon name="chat" />Conversar sobre este documento</Button>
      </div>
      {!ultima.chave && <p className="muted small">A API não forneceu uma referência válida para consultar este documento.</p>}
      {aberto && <div className="triage-result">
        <p className="muted small">Documento: {resultado.documento_id}</p>
        <p><strong>Encaminhado para</strong><br />{resultado.destino_principal}</p>
        <p><strong>Confiança da análise</strong><br />{resultado.score_confianca.toLocaleString('pt-BR', { style: 'percent', maximumFractionDigits: 1 })}</p>
        <p>{resultado.justificativa}</p>
        {resultado.classificacao === 'urgencia' && <p className="muted small">{resultado.alerta_enviado ? 'Alerta confirmado pelo webhook.' : 'Alerta sem confirmação de envio.'}</p>}
        <dl>{Object.entries(resultado.dados_extraidos).map(([campo, valor]) => <div key={campo}><dt>{campo === 'medico_responsavel' ? 'Médico responsável' : campo.replaceAll('_', ' ')}</dt><dd>{formatar(valor)}</dd></div>)}</dl>
        <details><summary>JSON da triagem</summary><pre>{JSON.stringify(resultado, null, 2)}</pre></details>
      </div>}
    </>}
  </Panel>
}
