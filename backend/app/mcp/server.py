from urllib.parse import urlparse

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from app.auth.identity import READ
from app.auth.verifier import DarkroomTokenVerifier, EngineGetter
from app.config import Settings
from app.mcp.read_tools import register_read_tools


def build_mcp(settings: Settings, engine: EngineGetter) -> MCPServer:
    """MCP server that accepts PATs and OAuth access tokens issued for `<base>/mcp`."""
    issuer = settings.public_base_url.rstrip("/")
    resource = f"{issuer}/mcp"
    mcp = MCPServer(
        "darkroom",
        token_verifier=DarkroomTokenVerifier(engine, resource),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer),
            resource_server_url=AnyHttpUrl(resource),
            required_scopes=[READ],
            validate_token_resource=True,
        ),
    )

    register_read_tools(mcp, engine)

    @mcp.tool()
    def ping() -> str:
        """Check that the Darkroom MCP server is reachable."""
        return "pong"

    return mcp


def transport_security(settings: Settings) -> TransportSecuritySettings:
    """Allow only the public host (DNS-rebinding protection)."""
    parsed = urlparse(settings.public_base_url)
    host = parsed.hostname or ""
    return TransportSecuritySettings(
        allowed_hosts=[host, f"{host}:*"],
        allowed_origins=[f"{parsed.scheme}://{parsed.netloc}"],
    )
