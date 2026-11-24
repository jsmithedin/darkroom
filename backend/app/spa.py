from pathlib import Path

from starlette.responses import FileResponse, JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

# Paths owned by the MCP app rather than the frontend.
MCP_PREFIXES = ("/mcp", "/.well-known")

# Vite puts a content hash in every file name under /assets, so those never change.
# Everything else (index.html, the manifest, icons) must be revalidated on each visit so
# a new deploy is picked up; FileResponse already sends ETag and Last-Modified for that.
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
REVALIDATE = {"Cache-Control": "no-cache"}


def _owned_by(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == p or path.startswith(p + "/") for p in prefixes)


class RootApp:
    """Catch-all mounted last: sends MCP paths to the MCP app, everything else to the SPA.

    Unknown `/api` and `/oauth` paths get a JSON 404.
    """

    def __init__(self, mcp_app: ASGIApp, dist: Path) -> None:
        self.mcp_app = mcp_app
        self.dist = dist.resolve()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.mcp_app(scope, receive, send)
            return
        path: str = scope["path"]
        if _owned_by(path, MCP_PREFIXES):
            await self.mcp_app(scope, receive, send)
            return
        await self._spa(path, scope["method"])(scope, receive, send)

    def _spa(self, path: str, method: str) -> Response:
        not_found = JSONResponse({"detail": "Not Found"}, status_code=404)
        if _owned_by(path, ("/api", "/oauth")) or method not in ("GET", "HEAD"):
            return not_found
        candidate = (self.dist / path.lstrip("/")).resolve()
        if candidate.is_file() and candidate.is_relative_to(self.dist):
            hashed = _owned_by(path, ("/assets",))
            return FileResponse(candidate, headers=IMMUTABLE if hashed else REVALIDATE)
        if _owned_by(path, ("/assets",)):
            return not_found
        index = self.dist / "index.html"
        if index.is_file():
            return FileResponse(index, headers=REVALIDATE)
        return not_found
