import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import App from './App'
import './index.css'
import SessaoProvider from './state/SessaoProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <SessaoProvider><App /></SessaoProvider>
    </BrowserRouter>
  </StrictMode>,
)
