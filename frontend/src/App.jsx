import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import RequireAuth from './components/RequireAuth'

const LoginPage = lazy(() => import('./pages/LoginPage'))
const CalendarPage = lazy(() => import('./pages/CalendarPage'))
const WorkoutListPage = lazy(() => import('./pages/WorkoutListPage'))
const WorkoutDetailPage = lazy(() => import('./pages/WorkoutDetailPage'))
const CandidatesPage = lazy(() => import('./pages/CandidatesPage'))
const AIReportsPage = lazy(() => import('./pages/AIReportsPage'))
const ReviewsPage = lazy(() => import('./pages/ReviewsPage'))
const TrendsPage = lazy(() => import('./pages/TrendsPage'))
const BodyMetricsPage = lazy(() => import('./pages/BodyMetricsPage'))
const BackfillPage = lazy(() => import('./pages/BackfillPage'))
const ScreenshotImportPage = lazy(() => import('./pages/ScreenshotImportPage'))
const FitImportPage = lazy(() => import('./pages/FitImportPage'))
const PlansPage = lazy(() => import('./pages/PlansPage'))
const CoachHubPage = lazy(() => import('./pages/CoachHubPage'))
const ImportHubPage = lazy(() => import('./pages/ImportHubPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))

function PageLoading() {
  return (
    <div role="status" className="flex min-h-48 items-center justify-center text-sm text-gray-500 dark:text-gray-400">
      <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600" aria-hidden="true" />
      正在加载页面…
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageLoading />}>
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
              <Route path="/coach" element={<CoachHubPage />} />
              <Route
                path="/coach-preferences"
                element={<Navigate to="/coach?tab=prefs" replace />}
              />
              <Route path="/import" element={<ImportHubPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
