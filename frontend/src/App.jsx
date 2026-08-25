import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import RequireAuth from './components/RequireAuth'
import { CurrentUserProvider } from './contexts/CurrentUserContext'
import LoginPage from './pages/LoginPage'
import CalendarPage from './pages/CalendarPage'
import WorkoutListPage from './pages/WorkoutListPage'
import WorkoutDetailPage from './pages/WorkoutDetailPage'
import CandidatesPage from './pages/CandidatesPage'
import AIReportsPage from './pages/AIReportsPage'
import ReviewsPage from './pages/ReviewsPage'
import TrendsPage from './pages/TrendsPage'
import BodyMetricsPage from './pages/BodyMetricsPage'
import BackfillPage from './pages/BackfillPage'
import ScreenshotImportPage from './pages/ScreenshotImportPage'
import FitImportPage from './pages/FitImportPage'
import PlansPage from './pages/PlansPage'
import SettingsPage from './pages/SettingsPage'
import AdminUsersPage from './pages/AdminUsersPage'
import AdminHealthPage from './pages/AdminHealthPage'
import LeaderboardPage from './pages/LeaderboardPage'

export default function App() {
  return (
    <BrowserRouter>
      <CurrentUserProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
            <Route element={<Layout />}>
              <Route path="/" element={<CalendarPage />} />
              <Route path="/workouts" element={<WorkoutListPage />} />
              <Route path="/workouts/:id" element={<WorkoutDetailPage />} />
              <Route path="/candidates" element={<CandidatesPage />} />
              <Route path="/ai-reports" element={<AIReportsPage />} />
              <Route path="/reviews" element={<ReviewsPage />} />
              <Route path="/trends" element={<TrendsPage />} />
              <Route path="/body-metrics" element={<BodyMetricsPage />} />
              <Route path="/backfill" element={<BackfillPage />} />
              <Route path="/screenshot-import" element={<ScreenshotImportPage />} />
              <Route path="/fit-import" element={<FitImportPage />} />
              <Route path="/plans" element={<PlansPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/admin/users" element={<AdminUsersPage />} />
              <Route path="/admin/health" element={<AdminHealthPage />} />
              <Route path="/leaderboard" element={<LeaderboardPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </CurrentUserProvider>
    </BrowserRouter>
  )
}
