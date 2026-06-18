import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './AuthContext'
import { nextAfterAuth } from './invite'
import { ProtectedRoute } from './ProtectedRoute'
import { Login } from './pages/Login'
import { Signup } from './pages/Signup'
import { Dashboard } from './pages/Dashboard'
import { Settings } from './pages/Settings'
import { Workspace } from './pages/Workspace'
import { NewWorkspace } from './pages/NewWorkspace'
import { AcceptInvite } from './pages/AcceptInvite'
import { Compare } from './pages/Compare'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
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
          {/* Catch-all: after Google SSO the app lands on "/" → route to the
              pending invite if there is one, else the dashboard. */}
          <Route path="*" element={<Navigate to={nextAfterAuth()} replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
