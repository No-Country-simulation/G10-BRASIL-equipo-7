import { Navigate, Route, Routes } from 'react-router'
import { lazy, Suspense } from 'react'
import AppLayout from './components/AppLayout'
import NovaTriagemPage from './pages/NovaTriagemPage'
const DocumentosPage = lazy(() => import('./pages/DocumentosPage'))

export default function App() {
  return <Routes>
    <Route element={<AppLayout />}>
      <Route index element={<Navigate to="/nova-triagem" replace />} />
      <Route path="nova-triagem" element={<NovaTriagemPage />} />
      <Route path="documentos" element={<Suspense fallback={<p role="status">Carregando Documentos…</p>}><DocumentosPage /></Suspense>} />
      <Route path="*" element={<Navigate to="/nova-triagem" replace />} />
    </Route>
  </Routes>
}
