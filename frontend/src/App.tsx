import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { Login } from "./pages/Login";
import { LogRoll } from "./pages/LogRoll";
import { Reference } from "./pages/Reference";
import { Settings } from "./pages/Settings";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<AppShell />}>
          <Route index element={<LogRoll />} />
          <Route path="/reference" element={<Reference />} />
          <Route path="/reference/:kind" element={<Reference />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<p>Not found.</p>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
