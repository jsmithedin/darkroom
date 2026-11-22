import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "../api/health";
import { useMe } from "../api/hooks";

export function Home() {
  const me = useMe();
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth });
  const state = health.isError ? "unreachable" : health.data ? (health.data.db ? "ok" : "database down") : "checking";
  return (
    <>
      <h1>Hello{me.data ? `, ${me.data.name}` : ""}</h1>
      <p>Backend: {state}</p>
    </>
  );
}
