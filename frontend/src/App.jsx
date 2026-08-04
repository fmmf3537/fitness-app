import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import RequireAuth from './components/RequireAuth'
import LoginPage from './pages/LoginPage'
import CalendarPage from './pages/CalendarPage'
import WorkoutListPage from './pages/WorkoutListPage'
import WorkoutDetailPage from './pages/WorkoutDetailPage'
import CandidatesPage from './pages/CandidatesPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route path="/" element={<CalendarPage />} />
            <Route path="/workouts" element={<WorkoutListPage />} />
            <Route path="/workouts/:id" element={<WorkoutDetailPage />} />
            <Route path="/candidates" element={<CandidatesPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
