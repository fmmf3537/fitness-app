import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import RequireAuth from './components/RequireAuth'
import LoginPage from './pages/LoginPage'
import CalendarPage from './pages/CalendarPage'
import WorkoutListPage from './pages/WorkoutListPage'
import WorkoutDetailPage from './pages/WorkoutDetailPage'
import CandidatesPage from './pages/CandidatesPage'
import AIReportsPage from './pages/AIReportsPage'
import TrendsPage from './pages/TrendsPage'
import BodyMetricsPage from './pages/BodyMetricsPage'
import BackfillPage from './pages/BackfillPage'
import SettingsPage from './pages/SettingsPage'

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
            <Route path="/ai-reports" element={<AIReportsPage />} />
            <Route path="/trends" element={<TrendsPage />} />
            <Route path="/body-metrics" element={<BodyMetricsPage />} />
            <Route path="/backfill" element={<BackfillPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
