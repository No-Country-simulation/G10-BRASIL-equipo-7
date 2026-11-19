import { z } from 'zod'
import { detalheDocumentoSchema, itemDocumentoSchema, objetosExclusaoSchema } from './contratos'
import type { ObjetosExclusao, Referencia, Rota } from './contratos'

export class ExclusaoParcial extends Error {
  constructor(public objetos: ObjetosExclusao) { super('Exclusão incompleta. Confira os arquivos pendentes antes de tentar novamente.') }
}
const caminho = (ref: Referencia) => `/documentos/${ref.categoria}/${encodeURIComponent(ref.chave)}`
async function consultar<T>(url: string, consumir: (resposta: Response) => Promise<T>, signal?: AbortSignal, method = 'GET') {
  const controle = new AbortController()
  const cancelar = () => controle.abort()
  signal?.addEventListener('abort', cancelar, { once: true })
  if (signal?.aborted) cancelar()
  const prazo = setTimeout(cancelar, 30_000)
  try {
    const resposta = await fetch(`/api${url}`, { method, signal: controle.signal })
    if (!resposta.ok) {
      if (method === 'DELETE' && resposta.status === 503) {
        const dados = await resposta.json().catch(() => null)
        const parcial = objetosExclusaoSchema.safeParse(dados?.detail)
        if (parcial.success) throw new ExclusaoParcial(parcial.data)
      }
      throw Error(resposta.status === 404 ? 'Documento não encontrado. Ele pode ter sido movido ou excluído.' : 'Não foi possível acessar os documentos. O serviço pode estar indisponível.')
    }
    return await consumir(resposta)
  } catch (erro) {
    if (signal?.aborted) throw new DOMException('Consulta cancelada', 'AbortError')
    if (controle.signal.aborted) throw Error('A consulta demorou mais que o esperado. Tente novamente.')
    if (erro instanceof TypeError) throw Error('Não foi possível conectar à API de documentos.')
    throw erro
  } finally { clearTimeout(prazo); signal?.removeEventListener('abort', cancelar) }
}
const json = <T>(schema: z.ZodType<T>) => async (resposta: Response) => {
  const valor = schema.safeParse(await resposta.json().catch(() => null))
  if (!valor.success) throw Error('A API retornou dados de documentos inválidos.')
  return valor.data
}
export async function listarDocumentos(categoria: Rota, signal: AbortSignal) {
  const parametros = new URLSearchParams({ categoria })
  if (categoria === 'ambiguidade') parametros.set('situacao_revisao', 'pendentes')
  const itens = await consultar(`/documentos?${parametros}`, json(z.array(itemDocumentoSchema)), signal)
  if (itens.some((item) => item.categoria !== categoria) || new Set(itens.map((item) => item.chave)).size !== itens.length) throw Error('A listagem retornada não corresponde à categoria solicitada.')
  return itens
}
export async function obterDocumento(ref: Referencia, signal: AbortSignal) {
  const documento = await consultar(`${caminho(ref)}?incluir_revisao=true`, json(detalheDocumentoSchema), signal)
  if (documento.chave !== ref.chave || documento.categoria !== ref.categoria) throw Error('A resposta não corresponde ao documento selecionado.')
  return documento
}
export const obterOriginal = (ref: Referencia, signal: AbortSignal) => consultar(`${caminho(ref)}/original`, (resposta) => resposta.blob(), signal)
export async function excluirDocumento(ref: Referencia) {
  const resultado = await consultar(caminho(ref), json(objetosExclusaoSchema), undefined, 'DELETE')
  if (resultado.pendentes.length) throw new ExclusaoParcial(resultado)
  return resultado
}
