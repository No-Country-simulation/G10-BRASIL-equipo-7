import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { DetalheDocumento } from '../api/contratos'
import { obterOriginal } from '../api/documentos'
import useConsulta from '../state/useConsulta'
import Icon from './Icon'
import { Button, EmptyState } from './ui'

const tipos: Record<string, string> = { pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', json: 'application/json' }
const PdfDocumento = lazy(() => import('./PdfDocumento'))
export default function OriginalDocumento({ documento, acoes }: { documento: DetalheDocumento; acoes?: ReactNode }) {
  const [tentativa, setTentativa] = useState(0)
  const [ampliado, setAmpliado] = useState(false)
  const [erroImagem, setErroImagem] = useState<Blob | null>(null)
  const dialogo = useRef<HTMLDialogElement>(null)
  const carregar = useCallback((signal: AbortSignal) => obterOriginal({ categoria: documento.categoria, chave: documento.chave }, signal), [documento.categoria, documento.chave])
  const original = useConsulta(documento.original_disponivel ? carregar : null, tentativa)
  const [midia, setMidia] = useState<{ origem: Blob; url: string; tipo: string; texto: string | null; erro: string } | null>(null)
  useEffect(() => {
    const blob = original.dados
    if (!blob) return
    const tipo = tipos[documento.nome.split('.').pop()?.toLowerCase() ?? ''] || blob.type
    const url = URL.createObjectURL(new Blob([blob], { type: tipo }))
    let atual = true
    const base = { origem: blob, url, tipo, texto: null, erro: '' }
    if (tipo === 'application/json') {
      void blob.text().then((texto) => { if (atual) setMidia({ ...base, texto: JSON.stringify(JSON.parse(texto), null, 2) }) })
        .catch(() => { if (atual) setMidia({ ...base, erro: 'Não foi possível interpretar o JSON original. O download permanece disponível.' }) })
    } else {
      // A URL é um recurso externo criado no efeito e revogado pelo cleanup abaixo.
      // eslint-disable-next-line react/set-state-in-effect
      setMidia(base)
    }
    return () => { atual = false; URL.revokeObjectURL(url) }
  }, [original.dados, documento.nome])
  useEffect(() => { if (ampliado && !dialogo.current?.open) dialogo.current?.showModal() }, [ampliado])
  const atual = midia?.origem === original.dados ? midia : null
  const erro = original.erro || atual?.erro || (erroImagem && erroImagem === original.dados ? 'Não foi possível exibir a imagem. Tente novamente ou baixe o original.' : '')
  function previa() {
    if (!documento.original_disponivel) return <EmptyState title="Original não disponível">O arquivo não foi localizado para esta triagem.</EmptyState>
    if (erro) return <div role="alert" className="error-message"><p>{erro}</p><Button onClick={() => setTentativa((valor) => valor + 1)}>Tentar carregar original novamente</Button></div>
    if (!atual) return <p className="muted" role="status">Carregando original…</p>
    if (atual.tipo === 'application/json') return <pre className="original-json">{atual.texto}</pre>
    if (atual.tipo === 'image/png' || atual.tipo === 'image/jpeg') return <img className="original-image" src={atual.url} alt={`Original: ${documento.nome}`} onError={() => setErroImagem(atual.origem)} />
    if (atual.tipo === 'application/pdf') return <Suspense fallback={<p role="status">Preparando PDF…</p>}><PdfDocumento key={atual.url} blob={atual.origem} /></Suspense>
    return <EmptyState title="Prévia não disponível para este formato">Use o download para abrir o arquivo.</EmptyState>
  }
  return <>
    <div className="original-preview preview-loaded">{previa()}</div>
    <div className="actions preview-actions"><Button disabled={!atual} onClick={() => setAmpliado(true)}><Icon name="expand" />Ampliar</Button>
      {atual ? <a className="button" aria-label="Baixar original" href={atual.url} download={documento.nome || documento.chave}><Icon name="download" />Baixar</a> : <Button disabled aria-label="Baixar original"><Icon name="download" />Baixar</Button>}
      {acoes}
    </div>
    <dialog ref={dialogo} className="preview-dialog" aria-labelledby="titulo-original-ampliado" onClose={() => setAmpliado(false)}>
      <div className="panel-heading"><h2 id="titulo-original-ampliado">{documento.nome || documento.chave}</h2><Button onClick={() => dialogo.current?.close()}>Fechar ampliação</Button></div>
      {ampliado && <div className="original-preview preview-expanded">{previa()}</div>}
    </dialog>
  </>
}
