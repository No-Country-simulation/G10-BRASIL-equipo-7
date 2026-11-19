import { createContext, useContext } from 'react'
import type { useSessaoState } from './useSessaoState'

export const SessaoContext = createContext<ReturnType<typeof useSessaoState> | null>(null)
export function useSessao() {
  const sessao = useContext(SessaoContext)
  if (!sessao) throw Error('Sessão da interface indisponível.')
  return sessao
}
