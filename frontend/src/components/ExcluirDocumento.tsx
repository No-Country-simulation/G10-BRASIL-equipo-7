import { useEffect, useRef, useState } from 'react'
import { ExclusaoParcial, excluirDocumento } from '../api/documentos'
import type { Referencia } from '../api/contratos'
import Icon from './Icon'
import { Button } from './ui'

export default function ExcluirDocumento({ referencia, nome, onSuccess }: { referencia: Referencia; nome: string; onSuccess: () => void }) {
  const [confirmando, setConfirmando] = useState(false)
  const [aceito, setAceito] = useState(false)
  const [excluindo, setExcluindo] = useState(false)
  const [erro, setErro] = useState<Error | null>(null)
  const trava = useRef(false)
  const vivo = useRef(true)
  useEffect(() => { vivo.current = true; return () => { vivo.current = false } }, [])
  async function confirmar() {
    if (!aceito || trava.current) return
    trava.current = true; setExcluindo(true); setErro(null)
    try { await excluirDocumento(referencia); if (vivo.current) onSuccess() }
    catch (falha) { if (vivo.current) setErro(falha instanceof Error ? falha : Error('Não foi possível confirmar a exclusão. Atualize a lista antes de tentar novamente.')) }
    finally { trava.current = false; if (vivo.current) setExcluindo(false) }
  }
  return <>
    {!confirmando ? <Button variant="danger" onClick={() => setConfirmando(true)}><Icon name="trash" />Excluir documento</Button> : <section className="delete-confirmation" aria-label="Confirmar exclusão do documento">
      <strong>Excluir {nome}?</strong>
      <p>Serão apagados permanentemente o original, as triagens e o histórico de revisão associados, em todas as categorias.</p>
      <label><input type="checkbox" disabled={excluindo} checked={aceito} onChange={(event) => setAceito(event.target.checked)} /> Entendo que os arquivos serão excluídos permanentemente.</label>
      {erro && <div role="alert" className="error-message"><p>{erro.message}</p>{erro instanceof ExclusaoParcial && <details><summary>Detalhes da exclusão parcial</summary>
        <strong>Removidos</strong><ul>{erro.objetos.removidos.map((item) => <li key={`${item.bucket}/${item.objeto}`}>{item.bucket}/{item.objeto}</li>)}</ul>
        <strong>Pendentes</strong><ul>{erro.objetos.pendentes.map((item) => <li key={`${item.bucket}/${item.objeto}`}>{item.bucket}/{item.objeto}</li>)}</ul>
      </details>}</div>}
      <div className="actions"><Button variant="danger" disabled={!aceito || excluindo} onClick={() => void confirmar()}>{excluindo ? 'Excluindo…' : 'Confirmar exclusão'}</Button><Button disabled={excluindo} onClick={() => { setConfirmando(false); setAceito(false); setErro(null) }}>Cancelar exclusão</Button></div>
    </section>}
  </>
}
