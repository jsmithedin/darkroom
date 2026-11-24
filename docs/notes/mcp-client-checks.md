# MCP client verification (Task 6.7)

**Status: not yet done.** These checks need the deployed server at
`https://film.jamielab.uk` and real clients, so they are manual. Fill in the
results below.

## 1. Claude Code with a personal access token

1. Create a `films:write` token in the app (Settings).
2. `claude mcp add --transport http darkroom https://film.jamielab.uk/mcp --header "Authorization: Bearer <token>"`
3. Ask Claude Code to call `get_stock`.

Result:

## 2. claude.ai custom connector (OAuth)

1. Add the server as a custom connector; choose **Register automatically** (DCR).
2. Complete sign-in; confirm the consent page lists the scopes and the redirect
   `https://claude.ai/api/mcp/auth_callback`.
3. Call `get_stock` and `log_roll`; confirm the Activity page shows the connector name.

Result (registration method, redirect URIs used):

## 3. Claude Code with OAuth (no header)

Record the registration method and loopback redirect URI (ephemeral port) it used.
If OAuth is unworkable in Claude Code, document the PAT path as the supported route.
Known risk from `mcp-auth-revision.md`: Claude Code's published client document
declares portless loopback URIs; our DCR path matches redirect URIs exactly, so a
registered port-specific URI should work, but verify.

Result:
