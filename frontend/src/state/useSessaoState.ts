import { useRef, useState } from 'react'
import { conversar, triar, validarArquivo } from '../api/cliente'
import type { ContextoChat, Mensagem, MensagemExibida, PedidoChat, Rota, UltimaTriagem } from '../api/contratos'

const mensagemErro = (erro: unknown) => erro instanceof Error ? erro.message : 'Não foi possível concluir a operação.'

export function useSessaoState() {
  const [ultima, setUltima] = useState<UltimaTriagem | null>(null)
  const [triando, setTriando] = useState(false)
  const [erroTriagem, setErroTriagem] = useState('')
  const travaTriagem = useRef(false)
  const [mensagens, setMensagens] = useState<MensagemExibida[]>([])
  const [historico, setHistorico] = useState<Mensagem[]>([])
  const [contexto, setContexto] = useState<ContextoChat>(null)
  const [rascunho, setRascunho] = useState('')
  const [consultando, setConsultando] = useState(false)
  const [erroChat, setErroChat] = useState('')
  const [pendente, setPendente] = useState<PedidoChat | null>(null)
  const travaChat = useRef(false)
  const [categoriaDocumentos, setCategoriaDocumentos] = useState<Rota>('ambiguidade')

  async function enviarTriagem(arquivo: File, canal: string) {
    if (travaTriagem.current) return false
    travaTriagem.current = true
    setTriando(true); setErroTriagem('')
    try { setUltima(await triar(arquivo, canal)); return true }
    catch (erro) { setErroTriagem(mensagemErro(erro)); return false }
    finally { travaTriagem.current = false; setTriando(false) }
  }

  function trocarContexto(novo: ContextoChat) {
    if (travaChat.current) return
    if (novo?.tipo === 'anexo') {
      try { validarArquivo(novo.arquivo, true) }
      catch (erro) { setErroChat(mensagemErro(erro)); return }
    }
    setContexto(novo); setHistorico([]); setPendente(null); setErroChat('')
    if (novo?.tipo === 'documento') setRascunho(`Quero um resumo do documento ${novo.nome}.`)
  }

  function novaConversa() {
    if (travaChat.current) return
    trocarContexto(null); setMensagens([]); setRascunho('')
  }

  async function enviarMensagem(repetir = false) {
    if (travaChat.current) return
    const texto = rascunho.trim() || (contexto?.tipo === 'anexo' ? 'Este arquivo já existe na base de documentos?' : '')
    const pedido = repetir ? pendente : texto ? { mensagem: texto, historico: historico.slice(-__CHAT_LIMITS__.maxMensagens), contexto } : null
    if (!pedido) return
    travaChat.current = true
    setConsultando(true); setErroChat(''); setPendente(pedido)
    if (!repetir) {
      setMensagens((atuais) => [...atuais, { papel: 'usuario', conteudo: pedido.mensagem,
        anexo: pedido.contexto?.tipo === 'anexo' ? pedido.contexto.arquivo.name : undefined }])
      setRascunho('')
    }
    try {
      const resposta = await conversar(pedido)
      setMensagens((atuais) => [...atuais, { papel: 'assistente', conteudo: resposta.mensagem, resposta }])
      setHistorico([...pedido.historico, { papel: 'usuario', conteudo: pedido.mensagem } as Mensagem,
        { papel: 'assistente', conteudo: resposta.mensagem } as Mensagem].slice(-__CHAT_LIMITS__.maxMensagens))
      setPendente(null)
    } catch (erro) { setErroChat(mensagemErro(erro)) }
    finally { travaChat.current = false; setConsultando(false) }
  }

  return { ultima, triando, erroTriagem, enviarTriagem, mensagens, contexto, trocarContexto,
    rascunho, setRascunho, consultando, erroChat, pendente, enviarMensagem, novaConversa, categoriaDocumentos, setCategoriaDocumentos }
}
