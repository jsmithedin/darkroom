import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { SettingsLayout } from "./components/SettingsLayout";
import { DevTimes } from "./pages/DevTimes";
import { Login } from "./pages/Login";
import { LogRoll } from "./pages/LogRoll";
import { Purchases } from "./pages/Purchases";
import { Reference } from "./pages/Reference";
import { Settings } from "./pages/Settings";
import { SettingsBulk } from "./pages/SettingsBulk";
import { Stock } from "./pages/Stock";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<AppShell />}>
          <Route index element={<LogRoll />} />
          <Route path="/reference" element={<Reference />} />
          <Route path="/reference/:kind" element={<Reference />} />
          <Route path="/stock" element={<Stock />} />
          <Route path="/purchases" element={<Purchases />} />
          <Route path="/dev-times" element={<DevTimes />} />
          <Route path="/settings" element={<SettingsLayout />}>
            <Route index element={<Settings />} />
            <Route path="bulk" element={<SettingsBulk />} />
          </Route>
          <Route path="*" element={<p>Not found.</p>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
