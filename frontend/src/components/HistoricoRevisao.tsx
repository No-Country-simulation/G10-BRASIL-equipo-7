import { rotulos } from '../api/contratos'

export default function HistoricoRevisao({ decisao }: { decisao: Record<string, unknown> }) {
  const valor = (campo: string) => typeof decisao[campo] === 'string' && decisao[campo] ? String(decisao[campo]) : 'Não informado'
  const data = typeof decisao.decidido_em === 'string' ? new Date(decisao.decidido_em) : null
  return <section className="review-history" aria-label="Histórico da revisão"><h3>Revisão humana</h3>
    {decisao.dados_corrigidos != null && <p className="muted small">Dados extraídos corrigidos pelo revisor.</p>}
    <p><strong>Destino</strong><br />{decisao.destino === 'rotina' || decisao.destino === 'urgencia' ? rotulos[decisao.destino] : valor('classificacao_corrigida')}</p>
    {(['departamento', 'revisor', 'observacao'] as const).map((campo) => <p key={campo}><strong>{{ departamento: 'Departamento', revisor: 'Revisor', observacao: 'Observação' }[campo]}</strong><br />{valor(campo)}</p>)}
    <p><strong>Registrada em</strong><br />{data && !Number.isNaN(data.getTime()) ? data.toLocaleString('pt-BR') : valor('decidido_em')}</p>
    {decisao.acao !== 'encaminhar' ? <p className="muted small">Decisão anterior preservada, sem encaminhamento automático.</p>
      : decisao.destino === 'urgencia' && <p className="muted small">{decisao.alerta_status === 'enviado' ? 'Alerta confirmado pelo webhook.' : decisao.alerta_status === 'falha' ? 'Falha no alerta. O encaminhamento foi preservado.' : 'Envio do alerta sem confirmação final.'}</p>}
    {typeof decisao.aviso === 'string' && <p className="muted small">{decisao.aviso}</p>}
  </section>
}
