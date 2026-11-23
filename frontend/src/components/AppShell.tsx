import { NavLink, Outlet } from "react-router-dom";
import { useLogout, useMe } from "../api/hooks";

export function AppShell() {
  const me = useMe();
  const logout = useLogout();

  if (me.isPending) return <main><p>Loading…</p></main>;
  if (me.isError) return <main><p>Redirecting to sign in…</p></main>;

  return (
    <div className="shell">
      <header className="topbar">
        <strong className="brand">Darkroom</strong>
        <nav aria-label="Main">
          <NavLink to="/" end>Log</NavLink>
          <NavLink to="/stock">Stock</NavLink>
          <NavLink to="/purchases">Purchases</NavLink>
          <NavLink to="/dev-times">Dev times</NavLink>
          <NavLink to="/reference">Reference</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
        <button type="button" className="link" onClick={() => logout.mutate()}>
          Sign out
        </button>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
