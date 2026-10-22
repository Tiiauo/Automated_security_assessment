import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import AppLayout from './components/AppLayout'
import AttackPathsPage from './pages/AttackPathsPage'
import LoginPage from './pages/LoginPage'
import MonitorPage from './pages/MonitorPage'
import NotFoundPage from './pages/NotFoundPage'
import ProjectCreatePage from './pages/ProjectCreatePage'
import ProjectDetailPage from './pages/ProjectDetailPage'
import ProjectListPage from './pages/ProjectListPage'
import ReportPage from './pages/ReportPage'
import SettingsPage from './pages/SettingsPage'
import VulnerabilitiesPage from './pages/VulnerabilitiesPage'

function RequireAuth() {
  const { user } = useAuth()
  return user ? <Outlet /> : <Navigate to="/login" replace />
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/login" element={<LoginPage />} />

        <Route element={<RequireAuth />}>
          <Route element={<AppLayout />}>
            <Route path="/projects" element={<ProjectListPage />} />
            <Route path="/projects/new" element={<ProjectCreatePage />} />
            <Route path="/projects/:id" element={<ProjectDetailPage />} />
            <Route path="/projects/:id/monitor" element={<MonitorPage />} />
            <Route path="/projects/:id/vulnerabilities" element={<VulnerabilitiesPage />} />
            <Route path="/projects/:id/attack-paths" element={<AttackPathsPage />} />
            <Route path="/projects/:id/report" element={<ReportPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Route>

        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
