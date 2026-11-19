import { useState } from 'react'
import { Link } from 'react-router'
import Icon from '../components/Icon'
import RevisaoForm from '../components/RevisaoForm'
import { Button, EmptyState, PageHeader, Panel } from '../components/ui'

const categorias = [
  { id: 'urgencia', nome: 'Urgência', icone: 'warning', descricao: 'Ação imediata necessária' },
  { id: 'rotina', nome: 'Rotina', icone: 'check', descricao: 'Documentos de rotina' },
  { id: 'ambiguidade', nome: 'Ambiguidade', icone: 'help', descricao: 'Revisão humana necessária' },
] as const
type Categoria = typeof categorias[number]['id']
type Aba = 'resumo' | 'json' | 'revisao'

export default function DocumentosPage() {
  const [categoria, setCategoria] = useState<Categoria>('ambiguidade')
  const [aba, setAba] = useState<Aba>('resumo')
  const abas: Aba[] = categoria === 'ambiguidade' ? ['resumo', 'json', 'revisao'] : ['resumo', 'json']
  return <>
    <PageHeader title="Documentos" description="Consulte, confira e revise os documentos da base.">
      <Button disabled><Icon name="refresh" />Atualizar</Button>
      <Link className="button button-primary" to="/nova-triagem"><Icon name="plus" />Nova triagem</Link>
    </PageHeader>
    <div className="category-filters" role="group" aria-label="Categoria dos documentos">
      {categorias.map((item) => <button key={item.id} className={`category category-${item.id}`} title={item.descricao} aria-pressed={categoria === item.id} onClick={() => { setCategoria(item.id); setAba('resumo') }}>
        <Icon name={item.icone} size={18} /><strong>{item.nome}</strong>
      </button>)}
    </div>
    <div className="documents-grid">
      <Panel title="Arquivos" className="files-panel">
        <label className="search-field"><Icon name="search" /><input type="search" placeholder="Buscar pelo nome" aria-label="Buscar documentos pelo nome" disabled /></label>
        <EmptyState title="Documentos ainda não carregados">A lista desta categoria será consultada na base após a integração.</EmptyState>
      </Panel>
      <Panel title="Documento original" className="original-panel">
        <div className="original-preview"><Icon name="file" size={48} /><EmptyState title="Selecione um documento">A prévia do PDF, imagem ou JSON aparecerá aqui.</EmptyState></div>
        <div className="actions preview-actions"><Button disabled><Icon name="expand" />Ampliar</Button><Button disabled><Icon name="download" />Baixar original</Button></div>
        <Button variant="danger" disabled><Icon name="trash" />Excluir documento</Button>
      </Panel>
      <Panel title="Resultado da triagem" className="result-panel">
        <div className="result-tabs" role="group" aria-label="Visualização do resultado">
          {abas.map((item) => <button key={item} aria-pressed={aba === item} onClick={() => setAba(item)}>{item === 'resumo' ? 'Resumo' : item === 'json' ? 'JSON' : 'Revisão'}</button>)}
        </div>
        {aba === 'revisao' ? <RevisaoForm /> : <EmptyState title={aba === 'json' ? 'JSON da triagem' : 'Nenhuma triagem selecionada'}>Selecione um documento para consultar {aba === 'json' ? 'a resposta completa.' : 'a classificação, o destino, a confiança e os dados extraídos.'}</EmptyState>}
      </Panel>
    </div>
  </>
}
