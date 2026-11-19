import { z } from 'zod'
import { chaveSchema, chatSchema, triagemSchema } from './contratos'
import type { PedidoChat, UltimaTriagem } from './contratos'

export const formatos = '.pdf,.png,.jpg,.jpeg,.json'
const mimes: Record<string, string> = { pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', json: 'application/json' }

export function validarArquivo(arquivo: File, chat = false) {
  const tipo = mimes[arquivo.name.split('.').pop()?.toLowerCase() ?? '']
  if (!tipo || (arquivo.type && arquivo.type !== 'application/octet-stream' && arquivo.type !== tipo)) throw Error('Escolha um PDF, PNG, JPG, JPEG ou JSON válido.')
  if (!arquivo.size) throw Error('O arquivo está vazio. Escolha outro documento.')
  if (chat && arquivo.size > __CHAT_LIMITS__.maxAnexoMb * 1024 * 1024) throw Error(`O anexo do chat deve ter até ${__CHAT_LIMITS__.maxAnexoMb} MB.`)
  return arquivo.type ? arquivo : new File([arquivo], arquivo.name, { type: tipo })
}

async function solicitar<T>(caminho: string, corpo: FormData, schema: z.ZodType<T>) {
  const controle = new AbortController()
  const prazo = setTimeout(() => controle.abort(), 75_000)
  try {
    const resposta = await fetch(`/api${caminho}`, { method: 'POST', body: corpo, signal: controle.signal })
    if (!resposta.ok) {
      const mensagens: Record<number, string> = {
        400: 'O arquivo está vazio ou a requisição não pôde ser processada.',
        413: 'O anexo excede o limite de tamanho permitido.',
        415: 'Formato não suportado. Escolha PDF, PNG, JPG, JPEG ou JSON.',
        422: 'A API não aceitou os dados. Confira os campos e o arquivo.',
      }
      throw Error(mensagens[resposta.status] ?? `Serviço indisponível (HTTP ${resposta.status}). Tente novamente em instantes.`)
    }
    const validado = schema.safeParse(await resposta.json().catch(() => null))
    if (!validado.success) throw Error('A API retornou uma resposta inválida. Não foi possível confirmar a operação.')
    return { dados: validado.data, headers: resposta.headers }
  } catch (erro) {
    if (controle.signal.aborted) throw Error(caminho === '/triagem'
      ? 'A triagem demorou mais que o esperado. Confira Documentos antes de reenviar o arquivo.'
      : 'A consulta demorou mais que o esperado. Tente novamente.')
    if (erro instanceof TypeError) throw Error('Não foi possível conectar à API. Verifique se o servidor está disponível.')
    throw erro
  } finally { clearTimeout(prazo) }
}

export async function triar(arquivo: File, canal: string): Promise<UltimaTriagem> {
  const corpo = new FormData()
  corpo.append('arquivo', validarArquivo(arquivo))
  corpo.append('canal_origem', canal)
  const { dados, headers } = await solicitar('/triagem', corpo, triagemSchema)
  const chave = chaveSchema.safeParse(headers.get('X-Documento-Chave'))
  return { nome: arquivo.name, resultado: dados, chave: chave.success ? chave.data : null }
}

export async function conversar(pedido: PedidoChat) {
  const corpo = new FormData()
  corpo.append('mensagem', pedido.mensagem)
  corpo.append('historico', JSON.stringify(pedido.historico))
  corpo.append('referencias', JSON.stringify(pedido.contexto?.tipo === 'documento' ? [pedido.contexto.referencia] : []))
  if (pedido.contexto?.tipo === 'anexo') corpo.append('arquivo', validarArquivo(pedido.contexto.arquivo, true))
  return (await solicitar('/chat', corpo, chatSchema)).dados
}
