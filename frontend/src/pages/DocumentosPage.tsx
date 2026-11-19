import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { chaveSchema, rotaSchema, triagemSchema } from '../api/contratos'
import { listarDocumentos, obterDocumento } from '../api/documentos'
import type { Rota } from '../api/contratos'
import { useSessao } from '../state/sessao'
import useConsulta from '../state/useConsulta'
import ExcluirDocumento from '../components/ExcluirDocumento'
import Icon from '../components/Icon'
import OriginalDocumento from '../components/OriginalDocumento'
import ResumoTriagem from '../components/ResumoTriagem'
import RevisaoForm from '../components/RevisaoForm'
import { Button, EmptyState, PageHeader, Panel } from '../components/ui'

const categorias = [
  { id: 'urgencia', nome: 'Urgência', icone: 'warning' },
  { id: 'rotina', nome: 'Rotina', icone: 'check' },
  { id: 'ambiguidade', nome: 'Ambiguidade', icone: 'help' },
] as const
type Aba = 'resumo' | 'json' | 'revisao'
const formatos: Record<string, string> = { pdf: 'Documento PDF', png: 'Imagem PNG', jpg: 'Imagem JPEG', jpeg: 'Imagem JPEG', json: 'Documento JSON' }
function useDetalhe(categoria: Rota, chave: string | null, versao: number) {
  const carregar = useCallback((signal: AbortSignal) => obterDocumento({ categoria, chave: chave ?? '' }, signal), [categoria, chave])
  return useConsulta(chave ? carregar : null, versao)
}

export default function DocumentosPage() {
  const { categoriaDocumentos, setCategoriaDocumentos } = useSessao()
  const [parametros, setParametros] = useSearchParams()
  const rota = rotaSchema.safeParse(parametros.get('categoria'))
  const categoria = rota.success ? rota.data : categoriaDocumentos
  const categoriaValida = !parametros.has('categoria') || rota.success
  const alvo = parametros.get('chave')
  const chaveValida = alvo === null || chaveSchema.safeParse(alvo).success
  const [versao, setVersao] = useState(0)
  const [busca, setBusca] = useState('')
  const [escolhida, setEscolhida] = useState<string | null>(null)
  const [aba, setAba] = useState<Aba>('resumo')
  const [aviso, setAviso] = useState('')
  useEffect(() => { if (categoriaValida) setCategoriaDocumentos(categoria) }, [categoria, categoriaValida, setCategoriaDocumentos])
  const carregarLista = useCallback((signal: AbortSignal) => listarDocumentos(categoria, signal), [categoria])
  const lista = useConsulta(categoriaValida ? carregarLista : null, versao)
  const repeticoes = new Map<string, number>()
  const itens = (lista.dados ?? []).map((item) => {
    const nome = item.nome || item.chave
    const numero = (repeticoes.get(nome) ?? 0) + 1
    repeticoes.set(nome, numero)
    return { ...item, rotulo: numero === 1 ? nome : `${nome} (${numero})` }
  })
  const filtrados = itens.filter((item) => item.rotulo.toLocaleLowerCase('pt-BR').includes(busca.trim().toLocaleLowerCase('pt-BR')))
  const alvoAusente = alvo !== null && lista.dados !== null && !itens.some((item) => item.chave === alvo)
  const chave = !categoriaValida || !chaveValida || alvoAusente || !lista.dados ? null
    : alvo ?? (filtrados.some((item) => item.chave === escolhida) ? escolhida : filtrados[0]?.chave ?? null)
  const detalhe = useDetalhe(categoria, chave, versao)
  const documento = detalhe.dados
  const resultado = triagemSchema.safeParse(documento?.resultado)
  const abas: Aba[] = categoria === 'ambiguidade' ? ['resumo', 'json', 'revisao'] : ['resumo', 'json']
  function mudarCategoria(nova: Rota) {
    setParametros({ categoria: nova }); setBusca(''); setEscolhida(null); setAba('resumo'); setAviso('')
  }
  return <>
    <PageHeader title="Documentos" description="Consulte os arquivos e os resultados da triagem.">
      <Button disabled={lista.carregando} onClick={() => { setVersao((valor) => valor + 1); setAviso('') }}><Icon name="refresh" />Atualizar</Button>
      <Link className="button button-primary" to="/nova-triagem"><Icon name="plus" />Nova triagem</Link>
    </PageHeader>
    {aviso && <p className="success-message" role="status">{aviso}</p>}
    <div className="category-filters" role="group" aria-label="Categoria dos documentos">
      {categorias.map((item) => <button key={item.id} className={`category category-${item.id}`} aria-pressed={categoria === item.id} onClick={() => mudarCategoria(item.id)}><Icon name={item.icone} size={18} /><strong>{item.nome}</strong></button>)}
    </div>
    {(!categoriaValida || !chaveValida || alvoAusente) && <div role="alert" className="error-message"><p>{!categoriaValida ? 'Categoria inválida.' : 'O documento citado não está disponível nesta categoria. Ele pode ter sido movido ou excluído.'}</p><Button onClick={() => { setParametros({ categoria }); setBusca(''); setEscolhida(null) }}>Mostrar lista de documentos</Button></div>}
    <div className="documents-grid">
      <Panel title="Arquivos" className="files-panel">
        <p className="muted small">{lista.dados ? `${itens.length} documento${itens.length === 1 ? '' : 's'}` : lista.erro ? 'Consulta indisponível' : 'Consultando a base'}</p>
        <label className="search-field"><Icon name="search" /><input type="search" placeholder="Buscar pelo nome" aria-label="Buscar documentos pelo nome" value={busca} onChange={(event) => { setBusca(event.target.value); setEscolhida(chave); if (alvo !== null) setParametros({ categoria }, { replace: true }) }} /></label>
        {lista.carregando && <p className="muted" role="status">Carregando documentos…</p>}
        {lista.erro && <p role="alert" className="error-message">{lista.erro}</p>}
        {lista.dados && !filtrados.length && <EmptyState title={itens.length ? 'Nenhum arquivo encontrado' : 'Nenhum documento nesta categoria'}>Selecione outra categoria ou envie um novo documento.</EmptyState>}
        <div className="file-list">{filtrados.map((item) => {
          const ext = (item.nome || item.chave).split('.').pop()?.toLowerCase() ?? ''
          return <button key={item.chave} className="file-row" aria-pressed={chave === item.chave} title={item.rotulo} onClick={() => { setEscolhida(item.chave); setAba('resumo'); if (alvo !== null) setParametros({ categoria }, { replace: true }) }}>
            <Icon name={['png', 'jpg', 'jpeg'].includes(ext) ? 'image' : 'file'} /><span><strong>{item.rotulo}</strong><small>{ext.toUpperCase()} · {formatos[ext] || 'Arquivo'}</small>{item.prioridade_revisao === 'alta' && <small className="priority-label">Revisão prioritária</small>}{item.erro && <small className="file-warning">Triagem com erro de leitura</small>}</span>
          </button>
        })}</div>
      </Panel>
      <Panel title="Documento original" className="original-panel">
        {documento ? <><OriginalDocumento key={`${categoria}/${chave}/${versao}`} documento={documento} /><ExcluirDocumento key={`${categoria}/${chave}`} referencia={{ categoria, chave: documento.chave }} nome={documento.nome || documento.chave} onSuccess={() => {
          setAviso('Documento e arquivos associados excluídos.'); setEscolhida(null); setBusca(''); setParametros({ categoria }, { replace: true }); setVersao((valor) => valor + 1)
        }} /></> : <EmptyState title={detalhe.carregando ? 'Carregando documento…' : 'Selecione um documento'}>{detalhe.erro || 'A prévia do PDF, imagem ou JSON aparecerá aqui.'}</EmptyState>}
      </Panel>
      <Panel title="Resultado da triagem" className="result-panel">
        <div className="result-tabs" role="group" aria-label="Visualização do resultado">{abas.map((item) => <button key={item} aria-pressed={aba === item} onClick={() => setAba(item)}>{item === 'resumo' ? 'Resumo' : item === 'json' ? 'JSON' : 'Revisão'}</button>)}</div>
        {detalhe.erro && <p className="error-message" role="alert">{detalhe.erro}</p>}
        {documento?.erro && <p className="error-message" role="alert">{documento.erro}</p>}
        {!documento ? <EmptyState title={detalhe.carregando ? 'Carregando triagem…' : 'Nenhuma triagem selecionada'}>Selecione um documento para consultar o resultado.</EmptyState>
          : aba === 'revisao' ? null : aba === 'json' ? <pre className="result-json">{JSON.stringify(documento.resultado, null, 2)}</pre>
            : resultado.success ? <ResumoTriagem resultado={resultado.data} decisao={documento.decisao} justificativaOriginal={documento.justificativa_original} />
              : <EmptyState title="Resumo indisponível">A triagem não segue o contrato atual. Confira o JSON ou o documento original.</EmptyState>}
        {documento && categoria === 'ambiguidade' && <div hidden={aba !== 'revisao'}><RevisaoForm key={`${categoria}/${chave}/${versao}`} documento={documento} ativo={aba === 'revisao'} onSuccess={(decisao) => {
          setAviso(`Documento encaminhado para ${decisao.destino === 'rotina' ? 'ROTINA' : 'URGÊNCIA'}.${decisao.destino === 'urgencia' && (decisao.alerta_status !== 'enviado' || decisao.aviso) ? ' O alerta não teve confirmação final.' : ''}`)
          setEscolhida(null); setBusca(''); setParametros({ categoria }, { replace: true }); setAba('resumo'); setVersao((valor) => valor + 1)
        }} /></div>}
      </Panel>
    </div>
  </>
}
