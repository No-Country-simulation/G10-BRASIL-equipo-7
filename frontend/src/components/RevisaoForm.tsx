import { useEffect, useRef, useState } from 'react'
import type { DetalheDocumento } from '../api/contratos'
import { triagemSchema } from '../api/contratos'
import { obterDocumento } from '../api/documentos'
import { decisaoRevisaoSchema, encaminharDocumento, ErroRevisao, obterOpcoesRevisao, pedidoRevisaoSchema } from '../api/revisao'
import type { DecisaoRevisao, PedidoRevisao } from '../api/revisao'
import { concluirDadosRevisao, iniciarDadosRevisao } from '../state/dadosRevisao'
import useConsulta from '../state/useConsulta'
import CamposRevisao from './CamposRevisao'
import HistoricoRevisao from './HistoricoRevisao'
import { Button } from './ui'

export default function RevisaoForm({ documento, ativo = true, onSuccess }: { documento: DetalheDocumento; ativo?: boolean; onSuccess: (decisao: DecisaoRevisao) => void }) {
  const [registro, setRegistro] = useState(documento.decisao ?? null)
  const [retomada, setRetomada] = useState<PedidoRevisao | null>(null)
  const [destino, setDestino] = useState<'rotina' | 'urgencia'>('rotina')
  const [departamento, setDepartamento] = useState('')
  const [revisor, setRevisor] = useState('')
  const [observacao, setObservacao] = useState('')
  const [editar, setEditar] = useState(false)
  const [dados, setDados] = useState(() => iniciarDadosRevisao(documento.resultado?.dados_extraidos))
  const [erro, setErro] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [conferindo, setConferindo] = useState(false)
  const [situacaoIncerta, setSituacaoIncerta] = useState(false)
  const [versaoOpcoes, setVersaoOpcoes] = useState(0)
  const trava = useRef(false), vivo = useRef(true), leitura = useRef<AbortController | null>(null)
  useEffect(() => { vivo.current = true; return () => { vivo.current = false; leitura.current?.abort() } }, [])
  const historico = registro !== null && registro.estado !== 'pendente'
  const opcoes = useConsulta(historico || !ativo ? null : obterOpcoesRevisao, versaoOpcoes)
  const pendente = registro?.estado === 'pendente' ? decisaoRevisaoSchema.safeParse(registro) : null
  const resultado = triagemSchema.safeParse(documento.resultado)
  const fixo = pendente?.success ? pendente.data : retomada
  const destinoAtual = fixo?.destino ?? destino
  const ocupado = enviando || conferindo

  async function conferir() {
    leitura.current?.abort()
    const controle = new AbortController(); leitura.current = controle
    setConferindo(true)
    try {
      const atual = await obterDocumento({ categoria: 'ambiguidade', chave: documento.chave }, controle.signal)
      if (!vivo.current || controle.signal.aborted) return
      const decisao = atual.decisao ?? null
      setRegistro(decisao)
      setSituacaoIncerta(false)
      const validada = decisaoRevisaoSchema.safeParse(decisao)
      if (validada.success && validada.data.estado === 'concluido' && validada.data.documento_id === documento.documento_id) onSuccess(validada.data)
    } catch {
      if (vivo.current && !controle.signal.aborted) setErro('Não foi possível conferir a situação. Mantenha a mesma decisão e confira novamente antes de retomar.')
    } finally { if (vivo.current && !controle.signal.aborted) setConferindo(false) }
  }
  async function enviar() {
    if (trava.current || ocupado || situacaoIncerta) return
    let pedido: PedidoRevisao
    try {
      pedido = fixo ?? pedidoRevisaoSchema.parse({ destino, ...(destino === 'rotina' ? { departamento } : {}), revisor, observacao,
        ...(editar ? { dados_corrigidos: concluirDadosRevisao(dados) } : {}) })
      if (!fixo && pedido.destino === 'rotina' && !opcoes.dados?.departamentos.includes(pedido.departamento ?? '')) throw Error('Selecione um departamento disponível.')
    } catch (falha) { setErro(falha instanceof Error && falha.name !== 'ZodError' ? falha.message : 'Confira os dados, o revisor e o departamento antes de confirmar.'); return }
    trava.current = true; setEnviando(true); setErro('')
    try {
      const decisao = await encaminharDocumento(documento.chave, pedido, documento.documento_id ?? '')
      if (vivo.current) onSuccess(decisao)
    } catch (falha) {
      if (!vivo.current) return
      setErro(falha instanceof Error ? falha.message : 'Não foi possível confirmar o encaminhamento.')
      if (!(falha instanceof ErroRevisao && falha.status === 422)) { setRetomada(pedido); setSituacaoIncerta(true); await conferir() }
    } finally { trava.current = false; if (vivo.current) setEnviando(false) }
  }
  if (historico) return <HistoricoRevisao decisao={registro} />
  if (pendente && (!pendente.success || pendente.data.documento_id !== documento.documento_id)) return <p role="alert" className="error-message">O registro pendente está incompatível. Não é possível alterá-lo por este formulário.</p>
  if (documento.erro || !resultado.success || resultado.data.documento_id !== documento.documento_id) return <p className="error-message">Não é possível revisar esta triagem ilegível ou incompatível. Confira o original.</p>
  const corrigir = fixo ? fixo.dados_corrigidos != null : editar
  return <form onSubmit={(event) => { event.preventDefault(); void enviar() }} aria-label="Revisão humana">
    {fixo && <p className="review-notice">Encaminhamento ainda sem confirmação final. Retome a mesma decisão; os campos estão bloqueados para preservar o registro.</p>}
    {opcoes.carregando && <p role="status" className="muted">Carregando departamentos…</p>}
    {opcoes.erro && <div role="alert" className="error-message"><p>{opcoes.erro}</p><Button onClick={() => setVersaoOpcoes((valor) => valor + 1)}>Tentar carregar departamentos novamente</Button></div>}
    <fieldset className="review-fields" disabled={ocupado || Boolean(fixo) || !opcoes.dados}>
      <legend className="sr-only">Dados da revisão humana</legend>
      <fieldset><legend>Destino</legend><div className="actions">{(['rotina', 'urgencia'] as const).map((valor) => <label key={valor}><input type="radio" name={`destino-${documento.chave}`} value={valor} checked={destinoAtual === valor} onChange={() => setDestino(valor)} /> {valor === 'rotina' ? 'Rotina' : 'Urgência'}</label>)}</div></fieldset>
      <label className="review-toggle"><input type="checkbox" checked={corrigir} onChange={(event) => setEditar(event.target.checked)} /> Corrigir dados extraídos</label>
      {corrigir && <CamposRevisao dados={fixo ? iniciarDadosRevisao(fixo.dados_corrigidos) : dados} onChange={setDados} />}
      {destinoAtual === 'rotina' ? <label className="field">Departamento<select required value={fixo?.departamento ?? departamento} onChange={(event) => setDepartamento(event.target.value)}>
        <option value="">Selecione o departamento</option>
        {fixo?.departamento && !opcoes.dados?.departamentos.includes(fixo.departamento) && <option value={fixo.departamento}>{fixo.departamento}</option>}
        {opcoes.dados?.departamentos.map((item) => <option key={item} value={item}>{item}</option>)}
      </select></label> : <p className="muted small">Departamento: {fixo?.departamento ?? opcoes.dados?.destino_urgencia}</p>}
      <label className="field">Revisor<input required maxLength={100} value={fixo?.revisor ?? revisor} onChange={(event) => setRevisor(event.target.value)} placeholder="Nome do revisor" /></label>
      <label className="field">Observação (opcional)<textarea rows={3} maxLength={1000} value={fixo?.observacao ?? observacao} onChange={(event) => setObservacao(event.target.value)} /></label>
    </fieldset>
    {erro && <p role="alert" className="error-message">{erro}</p>}
    {conferindo && <p role="status" className="muted">Conferindo situação registrada…</p>}
    {retomada && <Button disabled={ocupado} onClick={() => void conferir()}>Conferir situação da revisão</Button>}
    <Button variant="primary" className="full-width" type="submit" disabled={ocupado || situacaoIncerta || (!fixo && !opcoes.dados)}>{enviando ? 'Registrando encaminhamento…' : fixo ? 'Retomar encaminhamento' : 'Confirmar encaminhamento'}</Button>
    <p className="muted small">A revisão preserva o ID, a confiança da IA e o histórico. O alerta é tratado pelo backend.</p>
  </form>
}
