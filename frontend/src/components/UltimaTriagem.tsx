import { useState } from 'react'
import { Link } from 'react-router'
import { caminhoDocumento, rotulos } from '../api/contratos'
import { useSessao } from '../state/sessao'
import Icon from './Icon'
import ResumoTriagem from './ResumoTriagem'
import { Button, EmptyState, Panel } from './ui'

export default function UltimaTriagem() {
  const { ultima, consultando, trocarContexto } = useSessao()
  const [aberto, setAberto] = useState(false)
  const resultado = ultima?.resultado
  return <Panel title="Última triagem">
    {!ultima || !resultado ? <EmptyState title="Nenhuma triagem nesta sessão">O último documento analisado aparecerá aqui após o envio.</EmptyState> : <>
      <div className="file-summary"><Icon name="file" /><strong>{ultima.nome}</strong><span className={`route-badge badge-${resultado.classificacao}`}>{rotulos[resultado.classificacao]}</span></div>
      <div className="last-triage-actions">
        {ultima.chave ? <Link className="button" to={caminhoDocumento({ categoria: resultado.classificacao, chave: ultima.chave })}><Icon name="file" />Ver resultado</Link>
          : <Button aria-expanded={aberto} onClick={() => setAberto(!aberto)}><Icon name="file" />Ver resultado</Button>}
        <Button disabled={consultando || !ultima.chave} onClick={() => ultima.chave && trocarContexto({ tipo: 'documento', nome: ultima.nome,
          referencia: { categoria: resultado.classificacao, chave: ultima.chave } })}><Icon name="chat" />Conversar sobre este documento</Button>
      </div>
      {!ultima.chave && <p className="muted small">A API não forneceu uma referência válida para consultar este documento.</p>}
      <details open={aberto || undefined}><summary>Detalhes da última triagem</summary><ResumoTriagem resultado={resultado} /><pre className="result-json">{JSON.stringify(resultado, null, 2)}</pre></details>
    </>}
  </Panel>
}
