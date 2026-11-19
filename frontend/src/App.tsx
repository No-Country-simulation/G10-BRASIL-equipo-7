import { Navigate, Route, Routes } from 'react-router'
import AppLayout from './components/AppLayout'
import DocumentosPage from './pages/DocumentosPage'
import NovaTriagemPage from './pages/NovaTriagemPage'

export default function App() {
  return <Routes>
    <Route element={<AppLayout />}>
      <Route index element={<Navigate to="/nova-triagem" replace />} />
      <Route path="nova-triagem" element={<NovaTriagemPage />} />
      <Route path="documentos" element={<DocumentosPage />} />
      <Route path="*" element={<Navigate to="/nova-triagem" replace />} />
    </Route>
  </Routes>
}
