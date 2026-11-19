import type { RespostaChat } from '../api/contratos'
import { caminhoDocumento, rotulos } from '../api/contratos'
import { Link } from 'react-router'
import Icon from './Icon'

export default function FontesChat({ resposta }: { resposta: RespostaChat }) {
  const verificacao = resposta.verificacao_anexo
  return <>
    {verificacao && <div className={`verification verification-${verificacao.situacao}`}>
      {verificacao.situacao === 'encontrado' ? <><strong>Arquivo idêntico confirmado na base</strong>{verificacao.correspondencias.map((item) => <p key={`${item.localizacao}-${item.chave}`}>{item.nome} · {rotulos[item.localizacao]}</p>)}</>
        : verificacao.situacao === 'nao_encontrado' ? 'A verificação completa não encontrou um arquivo idêntico na base.'
          : <><strong>Verificação inconclusiva</strong><p>{verificacao.motivo}</p>{verificacao.correspondencias.map((item) => <p key={`${item.localizacao}-${item.chave}`}>Correspondência parcial: {item.nome} · {rotulos[item.localizacao]}</p>)}</>}
    </div>}
    {resposta.fontes.map((fonte, indice) => <div className="source-card" key={indice}>
      {fonte.trecho && <blockquote>{fonte.trecho}</blockquote>}
      <div className="file-summary"><Icon name="file" /><span>{fonte.nome}<small className="muted">{fonte.origem === 'base' ? rotulos[fonte.referencia.categoria] : 'Anexo temporário · não armazenado'}</small></span>
        {fonte.origem === 'base' && <Link className="button" to={caminhoDocumento(fonte.referencia)}>Abrir documento</Link>}
      </div>
    </div>)}
    {!resposta.cobertura.completa && <p className="muted small">Consulta parcial · {resposta.cobertura.motivo_limite}</p>}
  </>
}
