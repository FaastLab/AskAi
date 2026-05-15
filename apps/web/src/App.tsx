import { Routes, Route, Navigate } from "react-router-dom";
import { ChatPage } from "./pages/Chat";
import { DocumentsPage } from "./pages/Documents";

export default function App() {
  return (
    <div className="min-h-dvh">
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/chat/:sessionId" element={<ChatPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:documentId" element={<DocumentsPage />} />
      </Routes>
    </div>
  );
}
