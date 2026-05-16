import { Routes, Route, Navigate } from "react-router-dom";
import { AcceptInvitePage } from "./pages/AcceptInvite";
import { AdminPage } from "./pages/Admin";
import { ChatPage } from "./pages/Chat";
import { DocumentsPage } from "./pages/Documents";
import { LoginPage } from "./pages/Login";
import { SignupPage } from "./pages/Signup";
import { ValidatorPage } from "./pages/Validator";

export default function App() {
  return (
    <div className="min-h-dvh">
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/chat/:sessionId" element={<ChatPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:documentId" element={<DocumentsPage />} />
        <Route path="/validator" element={<ValidatorPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/accept" element={<AcceptInvitePage />} />
      </Routes>
    </div>
  );
}
