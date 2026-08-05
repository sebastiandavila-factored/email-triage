import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './AuthContext'
import { ProtectedRoute } from './ProtectedRoute'
import { Landing } from './pages/Landing'
import { Login } from './pages/Login'
import { Signup } from './pages/Signup'
import { Dashboard } from './pages/Dashboard'
import { Settings } from './pages/Settings'
import { Workspace } from './pages/Workspace'
import { Studio } from './pages/Studio'
import { NewWorkspace } from './pages/NewWorkspace'
import { AcceptInvite } from './pages/AcceptInvite'
import { Compare } from './pages/Compare'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public root: the landing page. Authenticated visitors are bounced
              into the app by the Landing component itself. */}
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <Settings />
              </ProtectedRoute>
            }
          />
          <Route
            path="/workspace"
            element={
              <ProtectedRoute>
                <Workspace />
              </ProtectedRoute>
            }
          />
          <Route
            path="/studio"
            element={
              <ProtectedRoute>
                <Studio />
              </ProtectedRoute>
            }
          />
          <Route
            path="/workspace/new"
            element={
              <ProtectedRoute>
                <NewWorkspace />
              </ProtectedRoute>
            }
          />
          <Route
            path="/compare"
            element={
              <ProtectedRoute>
                <Compare />
              </ProtectedRoute>
            }
          />
          {/* Not protected: handles the not-signed-in case itself (stash token → login). */}
          <Route path="/accept-invite" element={<AcceptInvite />} />
          {/* Unknown paths fall back to the landing; if authenticated, Landing
              forwards to the pending invite or the dashboard. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
