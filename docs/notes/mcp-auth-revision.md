# MCP authorization revision check

Checked 2026-11-23 for task 6.1.

The MCP site's latest authorization URL resolves to the dated **2026-07-28**
revision, confirming the revision inferred in the 2026-11-22 Darkroom design.
The discovery requirements, RFC 9207 issuer identification, and preference for
Client ID Metadata Documents (CIMD) over deprecated Dynamic Client Registration
(DCR) match section 7. [Current MCP authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
and [client registration requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration).

## Implications for section 7

- Claude's custom connector UI recommends its published identity (CIMD) and
  offers automatic registration (DCR). The connector docs say Claude
  normally selects CIMD when the authorization server advertises CIMD and
  public-client token authentication. DCR remains a documented way to connect.
  For Darkroom's planned DCR path, select **Register automatically** during task
  6.7. Supporting the recommended **Use Claude’s published identity** option
  requires adding CIMD to the authorization-server scope.
  [Custom connector setup](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
  and [connector authentication](https://claude.com/docs/connectors/building/authentication#dcr-and-cimd-details).
- Hosted Claude uses the exact callback `https://claude.ai/api/mcp/auth_callback`.
  Claude Code uses a loopback callback with an ephemeral port. Its published
  client document declares portless `http://localhost/callback` and
  `http://127.0.0.1/callback`. If Darkroom supports that document, section 7's
  exact matching rule needs an exception for the port of those native loopback
  redirects. Scheme, host and path still need to match the client's metadata,
  and the code exchange must use the exact URI from the authorization request.
  A DCR flow can match exactly when registration includes the chosen port.
  Verify the actual Claude Code registration and callback in task 6.7.
  [Claude callback requirements](https://claude.com/docs/connectors/building/authentication#callback-urls)
  and [Claude Code OAuth setup](https://code.claude.com/docs/en/mcp#use-a-fixed-oauth-callback-port).

The current documents establish these compatibility requirements. Their
publication dates do not establish that Claude changed behavior after the
Darkroom design was written on 2026-11-22.

## Task 6.1 implementation

Discovery advertises the public-client authorization code and refresh token
grants. The SDK serves protected-resource metadata with the same issuer as
the authorization server document. Migration 0010 adds OAuth clients,
hashed authorization codes, and hashed access and refresh tokens with a rotation
family ID.

Task 6.2 adds dynamic registration for public clients, Google sign-in and a
local consent form. Registration accepts exact HTTPS and HTTP loopback
callback URLs, with a shared limit of 20 registrations per minute.
Task 6.3 exchanges the resulting codes for tokens, and Task 6.4 enforces
bearer authentication.
