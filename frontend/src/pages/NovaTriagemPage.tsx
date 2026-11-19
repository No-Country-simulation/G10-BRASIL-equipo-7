import { useState } from 'react'
import { useSessao } from '../state/sessao'
import Assistente from '../components/Assistente'
import Icon from '../components/Icon'
import SelecionarArquivo from '../components/SelecionarArquivo'
import UltimaTriagem from '../components/UltimaTriagem'
import { Button, PageHeader, Panel } from '../components/ui'

export default function NovaTriagemPage() {
  const [arquivo, setArquivo] = useState<File | null>(null)
  const [canal, setCanal] = useState('Pronto-Socorro')
  const [erroArquivo, setErroArquivo] = useState('')
  const { triando, erroTriagem, enviarTriagem } = useSessao()
  return <>
    <PageHeader title="Triagem e assistente" description="Envie um documento ou converse sobre casos já triados." />
    <div className="triage-grid">
      <div className="triage-column">
        <Panel title="Nova triagem">
          <form onSubmit={(event) => { event.preventDefault(); if (arquivo) void enviarTriagem(arquivo, canal).then((sucesso) => { if (sucesso) setArquivo(null) }) }}>
            <SelecionarArquivo disabled={triando} onError={setErroArquivo} onFile={(novo) => { setArquivo(novo); setErroArquivo('') }} />
            {arquivo && <div className="selected-file"><Icon name="file" /><span>{arquivo.name}<small className="muted">{(arquivo.size / 1024).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} KB</small></span><Button variant="ghost" disabled={triando} onClick={() => setArquivo(null)}>Remover</Button></div>}
            <label className="field">Canal de origem<select disabled={triando} value={canal} onChange={(event) => setCanal(event.target.value)}><option>Pronto-Socorro</option><option>Ambulatório</option><option>Balcão</option></select></label>
            {(erroArquivo || erroTriagem) && <p className="error-message" role="alert">{erroArquivo || erroTriagem}</p>}
            <Button variant="primary" className="full-width" type="submit" disabled={!arquivo || triando}><Icon name="upload" />{triando ? 'Analisando documento…' : 'Enviar para triagem'}</Button>
            {triando && <p className="muted small" role="status">Aguarde a conclusão. Evite reenviar o mesmo arquivo.</p>}
          </form>
        </Panel>
        <UltimaTriagem />
      </div>
      <Assistente />
    </div>
  </>
}
