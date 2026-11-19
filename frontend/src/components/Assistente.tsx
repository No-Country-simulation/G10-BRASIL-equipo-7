import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import logo from '../assets/mediflow-icone.png'
import { useSessao } from '../state/sessao'
import FontesChat from './FontesChat'
import Icon from './Icon'
import SelecionarArquivo from './SelecionarArquivo'
import { Button, Panel } from './ui'

export default function Assistente() {
  const sessao = useSessao()
  const [erroArquivo, setErroArquivo] = useState('')
  const fim = useRef<HTMLDivElement>(null)
  const entrada = useRef<HTMLTextAreaElement>(null)
  const { mensagens, contexto, consultando, rascunho } = sessao
  const anexo = contexto?.tipo === 'anexo' ? contexto.arquivo : null
  const nomeContexto = anexo?.name ?? (contexto?.tipo === 'documento' ? contexto.nome : '')
  const extensao = nomeContexto.split('.').pop()?.toUpperCase()
  const divisor = anexo && anexo.size >= 1024 ** 2 ? 1024 ** 2 : anexo && anexo.size >= 1024 ? 1024 : 1
  const tamanho = anexo ? `${(anexo.size / divisor).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} ${divisor === 1 ? 'B' : divisor === 1024 ? 'KB' : 'MB'}` : ''
  useEffect(() => { fim.current?.scrollIntoView({ block: 'nearest' }) }, [mensagens, consultando])
  useEffect(() => { if (contexto?.tipo === 'documento') entrada.current?.focus() }, [contexto])
  return <Panel title="Assistente MediFlow" className="assistant-panel" action={<Button disabled={consultando} onClick={() => { sessao.novaConversa(); setErroArquivo('') }}><Icon name="plus" />Nova conversa</Button>}>
    <p className="muted assistant-description">Pergunte sobre documentos e casos já triados.</p>
    {contexto && <section className="chat-context" aria-label="Contexto da conversa">
      <div className="chat-context-icon"><Icon name={['PNG', 'JPG', 'JPEG'].includes(extensao ?? '') ? 'image' : 'file'} size={24} /></div>
      <div className="chat-context-details" role="status" aria-live="polite" aria-atomic="true">
        <span className="chat-context-label"><Icon name="check" size={15} />{anexo ? 'Anexo adicionado' : 'Documento selecionado'}</span>
        <strong>{nomeContexto}</strong>
        <p>{anexo ? `${extensao} · ${tamanho} · Temporário, não salvo na base` : 'Referência do documento para esta conversa'}</p>
      </div>
      <Button disabled={consultando} variant="ghost" onClick={() => { sessao.trocarContexto(null); setErroArquivo('') }}>Remover contexto</Button>
    </section>}
    <div className="conversation" role="log" aria-label="Conversa com o assistente" aria-live="polite">
      {!mensagens.length && <div className="assistant-welcome"><img src={logo} alt="" width="36" height="36" /><div><strong>Como posso ajudar?</strong><p>Consulte documentos e evidências das triagens.</p><p className="muted small">Experimente: “Quais casos estão em urgência?” ou “Encontre o arquivo laudo.pdf”.</p></div></div>}
      {mensagens.map((item, indice) => <div key={indice} className={`chat-message message-${item.papel}`}>
        {item.papel === 'assistente' && <img src={logo} alt="MediFlow" width="30" height="30" />}
        <div className="message-content"><Markdown skipHtml components={{ img: () => null, a: ({ children }) => <span>{children}</span> }}>{item.conteudo}</Markdown>
          {item.anexo && <p className="muted small">Anexo temporário · {item.anexo}</p>}
          {item.resposta && <FontesChat resposta={item.resposta} />}
        </div>
      </div>)}
      {consultando && <p className="loading-message" role="status">Consultando documentos…</p>}
      <div ref={fim} />
    </div>
    {(sessao.erroChat || erroArquivo) && <div className="error-message" role="alert"><p>{erroArquivo || sessao.erroChat}</p>{sessao.pendente && !erroArquivo && <Button disabled={consultando} onClick={() => void sessao.enviarMensagem(true)}>Tentar novamente</Button>}</div>}
    <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); setErroArquivo(''); void sessao.enviarMensagem() }}>
      <SelecionarArquivo chat disabled={consultando} onError={setErroArquivo} onFile={(arquivo) => { setErroArquivo(''); sessao.trocarContexto({ tipo: 'anexo', arquivo }) }} />
      <textarea ref={entrada} rows={2} aria-label="Mensagem para o assistente" placeholder="Pergunte ao assistente…" disabled={consultando} value={rascunho} onChange={(event) => sessao.setRascunho(event.target.value)}
        onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!consultando) { setErroArquivo(''); void sessao.enviarMensagem() } } }} />
      <Button type="submit" variant="primary" disabled={consultando || (!rascunho.trim() && contexto?.tipo !== 'anexo')} aria-label="Enviar mensagem"><Icon name="send" /></Button>
    </form>
    <p className="muted small">Anexos do chat são temporários (até {__CHAT_LIMITS__.maxAnexoMb} MB) e não iniciam triagem.</p>
  </Panel>
}
