import { useRef } from 'react'
import { formatos, validarArquivo } from '../api/cliente'
import Icon from './Icon'
import { Button } from './ui'

export default function SelecionarArquivo({ chat = false, disabled = false, onFile, onError }:
  { chat?: boolean; disabled?: boolean; onFile: (arquivo: File) => void; onError: (mensagem: string) => void }) {
  const entrada = useRef<HTMLInputElement>(null)
  function selecionar(arquivos: FileList | null) {
    if (disabled || !arquivos?.length) return
    try {
      if (arquivos.length !== 1) throw Error('Selecione apenas um arquivo por vez.')
      onFile(validarArquivo(arquivos[0], chat))
    } catch (erro) { onError(erro instanceof Error ? erro.message : 'Arquivo inválido.') }
  }
  const input = <input ref={entrada} type="file" accept={formatos} disabled={disabled} className="sr-only" tabIndex={-1}
    aria-label={chat ? 'Anexo temporário do chat' : 'Documento para triagem'}
    onChange={(event) => { selecionar(event.target.files); event.target.value = '' }} />
  if (chat) return <>{input}<Button variant="ghost" disabled={disabled} aria-label="Anexar documento temporário" title={`Anexo temporário · até ${__CHAT_LIMITS__.maxAnexoMb} MB`} onClick={() => entrada.current?.click()}><Icon name="clip" /></Button></>
  return <div className={`dropzone ${disabled ? 'is-busy' : ''}`} onDragOver={(event) => event.preventDefault()}
    onDrop={(event) => { event.preventDefault(); selecionar(event.dataTransfer.files) }}>
    {input}<Icon name="upload" size={32} /><strong>Arraste seu documento aqui</strong>
    <Button disabled={disabled} onClick={() => entrada.current?.click()}>Selecionar arquivo</Button>
    <p className="muted small">PDF, PNG, JPG, JPEG ou JSON</p>
  </div>
}
