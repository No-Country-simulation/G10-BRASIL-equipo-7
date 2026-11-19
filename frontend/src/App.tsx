import { Navigate, NavLink, Route, Routes } from 'react-router'

export default function App() {
  return (
    <div className="min-h-screen bg-zinc-950 p-6 text-zinc-100">
      <header className="mb-8 border-b border-zinc-700 pb-4">
        <p className="mb-4 text-xl font-semibold">MediFlow</p>
        <nav aria-label="Principal" className="flex flex-wrap gap-4">
          <NavLink to="/nova-triagem" className={({ isActive }) => isActive ? 'text-sky-300 underline' : 'text-zinc-300'}>
            Triagem e assistente
          </NavLink>
          <NavLink to="/documentos" className={({ isActive }) => isActive ? 'text-sky-300 underline' : 'text-zinc-300'}>
            Documentos
          </NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/nova-triagem" replace />} />
          <Route path="/nova-triagem" element={
            <section>
              <h1 className="mb-2 text-2xl font-semibold">Triagem e assistente</h1>
              <p>Área reservada para o envio de documentos e o assistente de consulta.</p>
            </section>
          } />
          <Route path="/documentos" element={
            <section>
              <h1 className="mb-2 text-2xl font-semibold">Documentos</h1>
              <p>Área reservada para consulta e revisão dos documentos.</p>
            </section>
          } />
          <Route path="*" element={<Navigate to="/nova-triagem" replace />} />
        </Routes>
      </main>
    </div>
  )
}
