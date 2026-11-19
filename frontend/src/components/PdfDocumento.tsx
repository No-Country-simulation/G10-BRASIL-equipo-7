import { useEffect, useRef, useState } from 'react'
import type { PDFDocumentProxy, PDFDocumentLoadingTask, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { Button } from './ui'

export default function PdfDocumento({ blob }: { blob: Blob }) {
  const [documento, setDocumento] = useState<PDFDocumentProxy | null>(null)
  const [pagina, setPagina] = useState(1)
  const [largura, setLargura] = useState(400)
  const [erro, setErro] = useState('')
  const canvas = useRef<HTMLCanvasElement>(null)
  const area = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let ativo = true
    let tarefa: PDFDocumentLoadingTask | undefined
    void import('pdfjs-dist').then(async (pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
      const bytes = new Uint8Array(await blob.arrayBuffer())
      if (!ativo) return
      tarefa = pdfjs.getDocument({ data: bytes, enableXfa: false, useSystemFonts: true })
      const pdf = await tarefa.promise
      if (ativo) setDocumento(pdf)
    }).catch(() => { if (ativo) setErro('Não foi possível abrir este PDF. Use Baixar original para conferir o arquivo.') })
    return () => { ativo = false; void tarefa?.destroy() }
  }, [blob])
  useEffect(() => {
    if (!area.current) return
    const observer = new ResizeObserver(([entrada]) => setLargura(Math.max(1, entrada.contentRect.width)))
    observer.observe(area.current)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    if (!documento || !canvas.current) return
    let ativo = true
    let renderizacao: RenderTask | undefined
    const tela = canvas.current
    void documento.getPage(pagina).then(async (folha) => {
      if (!ativo) return
      const viewport = folha.getViewport({ scale: largura / folha.getViewport({ scale: 1 }).width })
      const escala = Math.min(window.devicePixelRatio || 1, 2)
      tela.width = Math.ceil(viewport.width * escala); tela.height = Math.ceil(viewport.height * escala)
      tela.style.width = `${viewport.width}px`; tela.style.height = `${viewport.height}px`
      renderizacao = folha.render({ canvas: tela, viewport, transform: [escala, 0, 0, escala, 0, 0] })
      await renderizacao.promise
    }).catch((falha: unknown) => {
      if (ativo && !(falha instanceof Error && falha.name === 'RenderingCancelledException')) setErro('Não foi possível renderizar a página. O download permanece disponível.')
    })
    return () => { ativo = false; renderizacao?.cancel() }
  }, [documento, pagina, largura])
  return <div className="pdf-document" ref={area}>
    {erro ? <p className="error-message" role="alert">{erro}</p> : <>
      {documento ? <div className="pdf-toolbar"><Button disabled={pagina <= 1} onClick={() => setPagina((valor) => valor - 1)}>Anterior</Button><span>Página {pagina} de {documento.numPages}</span><Button disabled={pagina >= documento.numPages} onClick={() => setPagina((valor) => valor + 1)}>Próxima</Button></div>
        : <p role="status" className="muted">Preparando PDF…</p>}
      <canvas ref={canvas} aria-label={`Página ${pagina} do PDF original`} role="img" />
    </>}
  </div>
}
