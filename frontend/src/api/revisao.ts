import { z } from 'zod'
import { chaveSchema } from './contratos'

const texto = z.string().trim().min(1)
const opcional = texto.nullable().optional()
export const dadosClinicosSchema = z.object({
  paciente: z.object({ nome: opcional, idade: z.number().int().nonnegative().nullable().optional() }).strict().nullable().optional(),
  medico_responsavel: z.object({ nome: opcional, crm: opcional }).strict().nullable().optional(),
  medicamentos: z.array(z.object({ nome: opcional, dosagem: opcional, posologia: opcional }).strict()).nullable().optional(),
  exame_realizado: opcional, diagnostico_principal: opcional, cid_sugerido: opcional,
}).strict()
export const pedidoRevisaoSchema = z.object({
  destino: z.enum(['rotina', 'urgencia']), departamento: texto.max(200).nullable().optional(),
  revisor: texto.max(100), observacao: z.string().trim().max(1000), dados_corrigidos: dadosClinicosSchema.nullable().optional(),
}).refine((valor) => valor.destino !== 'rotina' || Boolean(valor.departamento), { message: 'Selecione o departamento.' })
export const decisaoRevisaoSchema = pedidoRevisaoSchema.safeExtend({
  acao: z.literal('encaminhar'), documento_id: texto, classificacao_original: z.literal('ambiguidade'),
  estado: z.enum(['pendente', 'concluido']), iniciado_em: z.iso.datetime({ offset: true }),
  decidido_em: z.iso.datetime({ offset: true }).optional(),
  alerta_status: z.enum(['em_envio', 'enviado', 'falha']).nullable().optional(), aviso: texto.nullable().optional(),
}).refine((valor) => valor.estado !== 'concluido' || Boolean(valor.decidido_em))
const opcoesSchema = z.object({ departamentos: z.array(texto).min(1), destino_urgencia: texto })
export type DadosClinicos = z.infer<typeof dadosClinicosSchema>
export type PedidoRevisao = z.infer<typeof pedidoRevisaoSchema>
export type DecisaoRevisao = z.infer<typeof decisaoRevisaoSchema>
export class ErroRevisao extends Error {
  constructor(mensagem: string, public status?: number) { super(mensagem) }
}
async function chamar(caminho: string, corpo?: PedidoRevisao, signal?: AbortSignal) {
  const controle = new AbortController()
  const cancelar = () => controle.abort()
  signal?.addEventListener('abort', cancelar, { once: true })
  if (signal?.aborted) cancelar()
  const prazo = setTimeout(cancelar, 30_000)
  try {
    const resposta = await fetch(`/api/auditoria${caminho}`, {
      method: corpo ? 'POST' : 'GET', signal: controle.signal,
      ...(corpo ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) } : {}),
    })
    const dados: unknown = await resposta.json().catch(() => null)
    if (!resposta.ok) {
      const mensagens: Record<number, string> = {
        404: 'Documento não encontrado. Atualize a lista.',
        409: 'Já existe outra decisão para este documento. Confira a situação registrada.',
        422: 'Confira os dados preenchidos e o departamento selecionado.',
        503: 'O encaminhamento não foi confirmado. Confira a situação antes de retomar a mesma decisão.',
      }
      throw new ErroRevisao(mensagens[resposta.status] || 'A revisão está indisponível. Tente novamente.', resposta.status)
    }
    return dados
  } catch (erro) {
    if (signal?.aborted) throw new DOMException('Consulta cancelada', 'AbortError')
    if (controle.signal.aborted) throw new ErroRevisao('A revisão demorou mais que o esperado. A operação pode continuar no servidor; confira a situação antes de retomar.')
    if (erro instanceof TypeError) throw new ErroRevisao('Não foi possível conectar à API de revisão. Confira a situação antes de repetir.')
    throw erro
  } finally { clearTimeout(prazo); signal?.removeEventListener('abort', cancelar) }
}
export async function obterOpcoesRevisao(signal: AbortSignal) {
  const opcoes = opcoesSchema.safeParse(await chamar('/opcoes', undefined, signal))
  if (!opcoes.success) throw Error('A API retornou opções de revisão inválidas.')
  return opcoes.data
}
export async function encaminharDocumento(chave: string, pedido: PedidoRevisao, documentoId: string) {
  const dados = await chamar(`/${encodeURIComponent(chaveSchema.parse(chave))}/encaminhamento`, pedidoRevisaoSchema.parse(pedido))
  const decisao = decisaoRevisaoSchema.safeParse(dados)
  if (!decisao.success || decisao.data.estado !== 'concluido' || decisao.data.documento_id !== documentoId
    || decisao.data.destino !== pedido.destino || decisao.data.revisor !== pedido.revisor
    || (pedido.destino === 'rotina' && decisao.data.departamento !== pedido.departamento)) throw new ErroRevisao('A API retornou uma confirmação incompatível. Confira a situação da revisão.')
  return decisao.data
}
