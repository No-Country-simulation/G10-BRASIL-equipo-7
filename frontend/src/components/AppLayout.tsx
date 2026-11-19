import { NavLink, Outlet } from 'react-router'
import logo from '../assets/mediflow-icone.png'
import Icon from './Icon'

export default function AppLayout() {
  return <div className="app-shell">
    <a className="skip-link" href="#conteudo">Ir para o conteúdo</a>
    <aside className="sidebar">
      <NavLink to="/nova-triagem" className="brand" aria-label="MediFlow — início">
        <img src={logo} alt="" width="48" height="48" /><span>MediFlow</span>
      </NavLink>
      <nav aria-label="Principal">
        <NavLink to="/nova-triagem"><Icon name="chat" />Triagem e assistente</NavLink>
        <NavLink to="/documentos"><Icon name="folder" />Documentos</NavLink>
      </nav>
      <p className="sidebar-footer">Demonstração · Dados fictícios</p>
    </aside>
    <main id="conteudo" className="workspace" tabIndex={-1}>
      <p className="preview-notice">Prévia visual · Envio, consulta e revisão serão conectados nas próximas etapas.</p>
      <Outlet />
    </main>
  </div>
}
