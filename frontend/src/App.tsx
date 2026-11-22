import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "./api/health";

export function App() {
  const { data, isError } = useQuery({ queryKey: ["health"], queryFn: fetchHealth });
  const state = isError ? "unreachable" : data ? (data.db ? "ok" : "database down") : "checking";
  return (
    <main>
      <h1>Darkroom</h1>
      <p>Backend: {state}</p>
    </main>
  );
}
