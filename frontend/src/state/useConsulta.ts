import { useEffect, useState } from 'react'

export default function useConsulta<T>(consultar: ((signal: AbortSignal) => Promise<T>) | null, versao = 0) {
  const vazio = { dados: null as T | null, erro: '', carregando: Boolean(consultar) }
  const [estado, setEstado] = useState({ ...vazio, consultar, versao })
  useEffect(() => {
    if (!consultar) return
    const controle = new AbortController()
    void consultar(controle.signal).then((dados) => {
      if (!controle.signal.aborted) setEstado({ dados, erro: '', carregando: false, consultar, versao })
    }).catch((erro: unknown) => {
      if (!controle.signal.aborted) setEstado({ dados: null, erro: erro instanceof Error ? erro.message : 'Não foi possível concluir a consulta.', carregando: false, consultar, versao })
    })
    return () => controle.abort()
  }, [consultar, versao])
  return estado.consultar === consultar && estado.versao === versao ? estado : vazio
}
