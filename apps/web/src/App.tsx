import { Routes, Route, Navigate } from "react-router-dom";
import { ChatPage } from "./pages/Chat";

export default function App() {
  return (
    <div className="min-h-dvh">
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/chat/:sessionId" element={<ChatPage />} />
      </Routes>
    </div>
  );
}
