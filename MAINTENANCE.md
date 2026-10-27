# Maintain and update PrintFlow

The portal MCP is its own service (`mcp`) with an HTTP health endpoint, bounded
logs and an independent restart policy. It shares the versioned web image but
runs a separate process. State is owned by the web API, so replacing the MCP
container does not delete the library or jobs.

| Command | Purpose |
| --- | --- |
| `python3 tools/printflowctl.py doctor` | Inspect OS, GPU hardware and runtime prerequisites |
| `python3 tools/printflowctl.py status` | Show container status and health |
| `python3 tools/printflowctl.py logs` | Show the latest 100 log lines |
| `python3 tools/printflowctl.py up` | Build and start the configured services |
| `python3 tools/printflowctl.py stop` | Stop services without printer commands |
| `python3 tools/printflowctl.py backup` | Quiesce containers, save private data, restart |
| `python3 tools/printflowctl.py update` | Build, back up, replace services and check health |
| `python3 tools/printflowctl.py models` | Download pinned local image-model weights |
| `python3 tools/printflowctl.py check-gpu` | Test the selected device inside the image worker |

On Windows with a Docker CLI, use `.venv/Scripts/python.exe` in place of `python3`.
For Docker Engine in WSL, run these commands inside the same WSL distribution.

## Update sequence

1. Finish active chat, design and slicing jobs. The maintenance command checks
   for them. It never sends start, pause, cancel, temperature or motion commands
   to a physical printer. Telemetry is briefly unavailable during replacement.
2. Back up before applying a new source release. Install the reviewed source
   release into the checkout while retaining `.env`, `.runtime`, `models`,
   `runs` and `weights`. `update` does not silently pull or overwrite source.
3. Run `update`. Images build before services stop. A build failure therefore
   leaves the old deployment running. After stopping, the command writes a private
   ZIP backup, recreates services, and waits for health checks.
4. If health checks fail, it requests the previous image IDs recorded before
   building. Check `status` and `logs`; rollback success is not assumed.

Do not prune old Docker images before confirming an update. Image rollback does
not undo data schema changes. This release has no destructive schema migration;
future migrations must provide a versioned migration and rollback procedure.
Pinned top-level dependency versions and model revisions live in the source.
Container tags are not immutable digests; record deployed image IDs and validate
new dependency/base-image builds before wider deployment.

## Data and recovery

Persistent paths:

- `.runtime/printflow/`: printer settings, library catalog, jobs, spool ledger,
  design history and conversations.
- `models/`: uploaded files and generated editable design revisions.
- `runs/`: native Orca projects, logs and G-code on the Windows host.
- `weights/triposr/`: downloadable model weights, excluded from normal backups.
- `.env` and `.runtime/bridge-token`: local connection secrets.

Backups include the above private state except model weights, plus a manifest
with the previous image IDs and deployment profile. Keep these ZIPs private;
they contain conversations, device details and tokens. The source archive from
`tools/package-source.py` is a different, allowlisted GitHub publication artifact.

To inspect or recover a backup without overwriting the current deployment:

```sh
python3 tools/printflowctl.py restore backups/printflow-TIMESTAMP.zip /path/to/new-recovery-directory
```

The destination must not exist. The tool rejects path traversal and symlinks.
Install the matching source version alongside the recovered data before starting
it, and verify model/library paths and printer connectivity. Keep the original
deployment stopped when switching to the recovered one to avoid two independent
spool ledgers observing the same printer.

## Updating Snapmaker Orca

The native bridge checks the installed binary against its validation record.
After an Orca update, run `tools/validate_bridge.py` on Windows before reusing
prior slicing validation claims. Preserve native material assignments and 3MF
painting. New firmware is not part of application maintenance.

## Validation status

Windows source/API tests, real CAD generation, native Orca comparisons and a
real CPU TripoSR reconstruction have passed in development. Docker Engine and
a WSL distribution were absent on that PC: container builds, update/rollback
against real containers and AMD inference remain target-environment checks.
Maintenance failure paths and backup/restore use isolated automated tests.
