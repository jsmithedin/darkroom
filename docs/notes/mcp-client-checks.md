# MCP client verification (Task 6.7)

**Status: closed on 2026-11-24 with the OAuth checks not run.** Only the
personal access token path was verified. The OAuth flow (claude.ai connector
and Claude Code without a header) is untested against the real clients, so
treat the PAT as the supported route until someone runs checks 2 and 3.

## 1. Claude Code with a personal access token (verified)

1. Create a `films:write` token in the app (Settings).
2. `claude mcp add --transport http darkroom https://film.jamielab.uk/mcp --header "Authorization: Bearer <token>"`
3. Ask Claude Code to call `get_stock`.

Result: a PAT named "Claude" worked from the Claude client. `get_stock` listed
the freezer; `record_stock_adjustment` (film "Test", format 110, counted 0)
fixed a -1 row and appeared on the Activity page as "Token: Claude" (the entry
records the token name, not an OAuth client).

## 2. claude.ai custom connector (OAuth) - NOT RUN

1. Add the server as a custom connector; choose **Register automatically** (DCR).
2. Complete sign-in; confirm the consent page lists the scopes and the redirect
   `https://claude.ai/api/mcp/auth_callback`.
3. Call `get_stock` and `log_roll`; confirm the Activity page shows the connector name.

Result (registration method, redirect URIs used):

## 3. Claude Code with OAuth (no header) - NOT RUN

Record the registration method and loopback redirect URI (ephemeral port) it used.
If OAuth is unworkable in Claude Code, document the PAT path as the supported route.
Known risk from `mcp-auth-revision.md`: Claude Code's published client document
declares portless loopback URIs; our DCR path matches redirect URIs exactly, so a
registered port-specific URI should work, but verify.

Result:
