export interface Health {
  status: string;
  db: boolean;
}

export async function fetchHealth(): Promise<Health> {
  const res = await fetch("/api/health");
  return res.json();
}
