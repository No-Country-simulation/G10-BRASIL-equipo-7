import logo from '../assets/mediflow-icone.png'
import Icon from '../components/Icon'
import { Button, EmptyState, PageHeader, Panel } from '../components/ui'

export default function NovaTriagemPage() {
  return <>
    <PageHeader title="Triagem e assistente" description="Envie um documento ou converse sobre casos já triados." />
    <div className="triage-grid">
      <div className="triage-column">
        <Panel title="Nova triagem">
          <div className="dropzone">
            <Icon name="upload" size={32} /><strong>Arraste seu documento aqui</strong>
            <Button disabled>Selecionar arquivo</Button><p className="muted small">PDF, PNG, JPG, JPEG ou JSON</p>
          </div>
          <label className="field">Canal de origem<select defaultValue="Pronto-Socorro"><option>Pronto-Socorro</option><option>Ambulatório</option><option>Balcão</option></select></label>
          <Button variant="primary" className="full-width" disabled><Icon name="upload" />Enviar para triagem</Button>
        </Panel>
        <Panel title="Última triagem">
          <EmptyState title="Nenhuma triagem nesta sessão">O último documento analisado aparecerá aqui após o envio.</EmptyState>
          <div className="last-triage-actions"><Button disabled><Icon name="file" />Ver resultado</Button><Button disabled><Icon name="chat" />Conversar sobre este documento</Button></div>
        </Panel>
      </div>
      <Panel title="Assistente MediFlow" className="assistant-panel" action={<Button disabled><Icon name="plus" />Nova conversa</Button>}>
        <p className="muted assistant-description">Pergunte sobre documentos e casos já triados.</p>
        <div className="conversation" aria-label="Conversa com o assistente">
          <div className="assistant-welcome"><img src={logo} alt="" width="36" height="36" /><div><strong>Como posso ajudar?</strong><p>Consulte documentos e evidências das triagens.</p><p className="muted small">Experimente: “Quais casos estão em urgência?” ou “Encontre o arquivo laudo.pdf”.</p></div></div>
        </div>
        <div className="chat-composer"><Button variant="ghost" disabled aria-label="Anexar documento temporário"><Icon name="clip" /></Button><textarea rows={1} aria-label="Mensagem para o assistente" placeholder="Pergunte ao assistente…" disabled /><Button variant="primary" disabled aria-label="Enviar mensagem"><Icon name="send" /></Button></div>
        <p className="muted small">Anexos do chat são temporários e não iniciam triagem.</p>
      </Panel>
    </div>
  </>
}
