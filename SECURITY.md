# Security

## Deployment boundary

PrintFlow Local is an experimental, single-user application for a trusted local
computer and network. It is not a hardened public hosting service. Do not expose
the web, MCP, CAD, image worker or host bridge ports to the internet. The web UI
is not a substitute for a multi-user authentication/authorization gateway.

The Windows host bridge uses a generated local token. Keep it in the ignored
runtime configuration and restrict network access to the required local services.
Container mode does not make the host or printer interface publicly safe.

## Data handling

- Keep `.env`, `.runtime/`, `runs/`, `weights/` and private backups out of Git.
- Do not publish printer addresses, account information, chat history or photos.
- Treat imported models, archives, web listings and generated tool inputs as
  untrusted data. Keep path, size, archive and parameter validation enabled.
- Codex/ChatGPT is an external account service. Prompts, selected evidence and
  relevant tool results can leave the PC when the assistant is used.
- Review prepared output and confirm the actual printer/material setup before
  starting a print. Do not remove active-print or clear-bed guards.

Source archives are allowlisted. Backup archives contain private state and may
contain tokens; do not confuse the two when sharing a reproducible example.
If a credential is exposed, revoke/rotate it with its provider and remove it
from affected files and history. Deleting a displayed message is not revocation.

## Report a vulnerability

Use the repository's **Security → Report a vulnerability** option for a private
report. Include the affected commit, minimal reproduction, impact and a redacted
example. Never post credentials, private backups or printer control endpoints in
a public issue. If private reporting is unavailable, open an issue requesting a
private contact channel without including exploit details or sensitive data.

Only the current `main` branch receives fixes; there is no security response SLA
or independently audited release. Update dependencies and native applications
deliberately, then repeat the relevant checks before deployment.
