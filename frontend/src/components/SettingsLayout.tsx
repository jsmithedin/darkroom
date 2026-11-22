import { NavLink, Outlet } from "react-router-dom";

/** Tabs shared by the settings screens. */
export function SettingsLayout() {
  return (
    <>
      <nav className="tabs" aria-label="Settings sections">
        <NavLink to="/settings" end>
          Access tokens
        </NavLink>
        <NavLink to="/settings/bulk">Bulk film</NavLink>
      </nav>
      <Outlet />
    </>
  );
}
