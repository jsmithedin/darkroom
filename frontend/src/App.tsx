import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { Reference } from "./pages/Reference";
import { Settings } from "./pages/Settings";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<AppShell />}>
          <Route index element={<Home />} />
          <Route path="/reference" element={<Reference />} />
          <Route path="/reference/:kind" element={<Reference />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<p>Not found.</p>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
