import { z } from 'zod'

const texto = z.string().trim().min(1)
export const rotaSchema = z.enum(['rotina', 'urgencia', 'ambiguidade'])
export const chaveSchema = z.string().min(1).refine((chave) => chave.trim() === chave && !chave.includes('/') && !chave.includes('\\')
  && chave !== '.' && chave !== '..' && [...chave].every((letra) => letra.charCodeAt(0) >= 32 && letra.charCodeAt(0) !== 127))
const referenciaSchema = z.object({ categoria: rotaSchema, chave: chaveSchema })
export const triagemSchema = z.object({
  documento_id: texto, classificacao: rotaSchema, destino_principal: texto,
  score_confianca: z.number().min(0).max(1), justificativa: texto,
  alerta_enviado: z.boolean(), dados_extraidos: z.record(z.string(), z.unknown()),
})
const fonteSchema = z.discriminatedUnion('origem', [
  z.object({ origem: z.literal('base'), nome: texto, referencia: referenciaSchema, trecho: texto.nullable() }),
  z.object({ origem: z.literal('anexo'), nome: texto, referencia: z.null(), trecho: texto.nullable() }),
])
const coberturaSchema = z.object({
  completa: z.boolean(), documentos_consultados: z.number().int().nonnegative(), motivo_limite: texto.nullable(),
}).refine((valor) => valor.completa === (valor.motivo_limite === null))
const verificacaoSchema = z.object({
  situacao: z.enum(['encontrado', 'nao_encontrado', 'inconclusivo']), busca_completa: z.boolean(), motivo: texto.nullable(),
  correspondencias: z.array(z.object({
    chave: chaveSchema, nome: texto, documento_id: texto.nullable(),
    localizacao: z.enum(['recebidos', 'urgencia', 'rotina', 'ambiguidade']),
  })),
}).refine((valor) => valor.situacao === 'inconclusivo'
  ? !valor.busca_completa && valor.motivo !== null
  : valor.busca_completa && valor.motivo === null && ((valor.situacao === 'encontrado') === (valor.correspondencias.length > 0)))
export const chatSchema = z.object({
  mensagem: texto, fontes: z.array(fonteSchema), cobertura: coberturaSchema, verificacao_anexo: verificacaoSchema.nullable(),
}).refine((valor) => !valor.verificacao_anexo || valor.verificacao_anexo.busca_completa || !valor.cobertura.completa)

export type Rota = z.infer<typeof rotaSchema>
export type Referencia = z.infer<typeof referenciaSchema>
export type ResultadoTriagem = z.infer<typeof triagemSchema>
export type RespostaChat = z.infer<typeof chatSchema>
export type Mensagem = { papel: 'usuario' | 'assistente'; conteudo: string }
export type ContextoChat = { tipo: 'anexo'; arquivo: File } | { tipo: 'documento'; nome: string; referencia: Referencia } | null
export type PedidoChat = { mensagem: string; historico: Mensagem[]; contexto: ContextoChat }
export type UltimaTriagem = { nome: string; resultado: ResultadoTriagem; chave: string | null }
export type MensagemExibida = Mensagem & { anexo?: string; resposta?: RespostaChat }
export const rotulos = { urgencia: 'Urgência', rotina: 'Rotina', ambiguidade: 'Ambiguidade', recebidos: 'Recebidos (sem triagem confirmada)' }
