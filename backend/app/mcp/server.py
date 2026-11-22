from urllib.parse import urlparse

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from app.config import Settings


def build_mcp() -> MCPServer:
    mcp = MCPServer("darkroom")

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
