import type { JSX } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { isAuthenticated } from "./lib/auth";
import { AcceptInvitePage } from "./pages/AcceptInvite";
import { AdminPage } from "./pages/Admin";
import { AuditPage } from "./pages/Audit";
import { ChatPage } from "./pages/Chat";
import { DocumentsPage } from "./pages/Documents";
import { LoginPage } from "./pages/Login";
import { PromptsPage } from "./pages/Prompts";
import { SecurityPage } from "./pages/Security";
import { SignupPage } from "./pages/Signup";
import { UsagePage } from "./pages/Usage";
import { ValidatorPage } from "./pages/Validator";

/**
 * Route guard — anything wrapped in this redirects unauthenticated visitors
 * to /login (preserving the intended path so we can bounce them back after
 * login). The API itself enforces auth too; this is purely a UX nicety so
 * users don't see empty/broken pages while every fetch 401s.
 */
function RequireAuth({ children }: { children: JSX.Element }) {
  const location = useLocation();
  if (!isAuthenticated()) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return children;
}

export default function App() {
  return (
    <div className="min-h-dvh">
      <Routes>
        {/* Public routes */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/accept" element={<AcceptInvitePage />} />

        {/* Protected routes */}
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<RequireAuth><ChatPage /></RequireAuth>} />
        <Route path="/chat/:sessionId" element={<RequireAuth><ChatPage /></RequireAuth>} />
        <Route path="/documents" element={<RequireAuth><DocumentsPage /></RequireAuth>} />
        <Route path="/documents/:documentId" element={<RequireAuth><DocumentsPage /></RequireAuth>} />
        <Route path="/validator" element={<RequireAuth><ValidatorPage /></RequireAuth>} />
        <Route path="/admin" element={<RequireAuth><AdminPage /></RequireAuth>} />
        <Route path="/audit" element={<RequireAuth><AuditPage /></RequireAuth>} />
        <Route path="/usage" element={<RequireAuth><UsagePage /></RequireAuth>} />
        <Route path="/prompts" element={<RequireAuth><PromptsPage /></RequireAuth>} />
        <Route path="/security" element={<RequireAuth><SecurityPage /></RequireAuth>} />

        {/* Catch-all — unknown paths bounce home (which RequireAuth then
            sends to /login if the visitor isn't authenticated). */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
