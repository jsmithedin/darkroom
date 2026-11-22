import { NavLink, Navigate, useParams } from "react-router-dom";
import { REF_KINDS } from "../api/reference";
import { RefList } from "../components/RefList";

export function Reference() {
  const { kind } = useParams();
  const current = REF_KINDS.find((k) => k.kind === kind);
  if (!current) return <Navigate to="/reference/cameras" replace />;

  return (
    <>
      <h1>Reference lists</h1>
      <nav className="tabs" aria-label="Reference lists">
        {REF_KINDS.map((k) => (
          <NavLink key={k.kind} to={`/reference/${k.kind}`}>
            {k.label}
          </NavLink>
        ))}
      </nav>
      <h2>{current.label}</h2>
      <RefList key={current.kind} kind={current.kind} singular={current.singular} />
    </>
  );
}
