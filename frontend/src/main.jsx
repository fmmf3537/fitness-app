import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { initDarkModeListener } from './utils/darkMode.js'

// 跟随系统偏好挂载 html.dark（设置页手动开关可后续复用 applyDarkClass）
initDarkModeListener()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
