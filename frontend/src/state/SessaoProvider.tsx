import type { ReactNode } from 'react'
import { SessaoContext } from './sessao'
import { useSessaoState } from './useSessaoState'

export default function SessaoProvider({ children }: { children: ReactNode }) {
  return <SessaoContext value={useSessaoState()}>{children}</SessaoContext>
}
