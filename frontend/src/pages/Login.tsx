export function Login() {
  return (
    <main className="login">
      <h1>Darkroom</h1>
      <p>Film photography tracker.</p>
      <a className="button primary" href="/api/auth/login">
        Sign in with Google
      </a>
    </main>
  );
}
