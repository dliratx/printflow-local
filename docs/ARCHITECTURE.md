# Architecture and data

[Project overview](../README.md) · [Installation](../INSTALL.md)

## Services

| Service | Native port | Container role | Responsibilities |
| --- | --- | --- | --- |
| Web | 8840 | `web` | Browser assets, library, jobs, persistence, printer adapters and workflow coordination. |
| Windows host | 8841 | Runs outside containers | Authenticated native Orca operations and Codex app-server integration. |
| Portal MCP | 8842 | `mcp` | Model Context Protocol tools backed by the web API; endpoint `/mcp`. |
| CAD | 8843 | `design` | Isolated CadQuery/Manifold geometry generation and assembly cutting. |
| Image-to-3D | 8844 | Optional `image3d` | Local TripoSR inference with separately downloaded weights. |

Native services default to loopback. Host/container deployments need a reachable
Windows host bridge and shared model paths. Published ports, worker health checks
and mounts are declared in `compose.yaml`; AMD overrides live in `deploy/`.
Do not expose these development services to the public internet.

## Source map

- `printflow/api.py`: portal API and workflow orchestration.
- `printflow/portal_mcp.py`: portal MCP tools.
- `printflow/host_bridge.py`, `printflow/codex.py`: host operations and assistant sessions.
- `printflow/printers.py`: printer adapter contract and official U1 integration.
- `u1_server.py`: bounded native U1 project/slicer bridge.
- `printflow/mesh_stream.py`, `printflow/previews.py`: model inspection and previews.
- `printflow/print_strategy.py`, `printflow/print_image.py`: preparation proposals and emitted-G-code images.
- `printflow/calibration*.py`: test catalog, geometry, evidence and reusable profiles.
- `printflow/assembly*.py`: assembly planning and solid partitioning.
- `web/static/`: browser UI and JavaScript modules; no frontend build tool required.
- `services/`, `deploy/`, `tools/`: worker images, deployment profiles and lifecycle tools.
- `tests/`: unit tests and synthetic fixtures.
- `vendor/snapmaker-u1-mcp/`: pinned upstream source with local changes and retained license.

## Preparation flow

1. Import a local STL or 3MF. Keep its original bytes and provenance.
2. Inspect geometry, saved settings, plate placement and material assignments.
3. Select actual material and compatible native/calibrated settings.
4. Prepare a project copy or compare deliberate variants through the host bridge.
5. Inspect emitted G-code, tools, supports, brim, tower and time/material estimates.
6. Separately confirm the clear bed and actual hotend mapping, then start a job.

The interactive viewer has display budgets; slicing must not depend on successful
interactive rendering. Prepared jobs retain the complete source geometry. Slicer
estimates are not physical evidence of finish, adhesion or strength.

The legacy `snapmaker-u1` MCP operates on saved project files. Only the portal's
printer adapter performs explicit printer actions. Preparation does not replace,
pause or cancel an existing print. Multi-printer plans never automatically start
the next part on a plate that has not been cleared.

## Persistent data

| Path | Contents | Public source? |
| --- | --- | --- |
| `.runtime/printflow/` | Printer configuration, model catalog, jobs, chats, calibration and spool records | No |
| `.runtime/bridge-token`, `.env` | Local service credentials | No |
| `models/` | Uploaded models, revisions, photos and generated assemblies | No |
| `models/calibration-assets/3DBenchy.stl` and `source.json` | Attributed benchmark and provenance | Yes, explicit exception |
| `runs/` | Native project copies, G-code, logs and reports | No |
| `weights/` | Downloaded inference weights | No |
| `backups/` | Private backup archives | No |

The source-only archive and private backup are different artifacts. Use the
[maintenance guide](../MAINTENANCE.md) for recovery; never attach a private backup
to a public issue. Codex account credentials remain in the host's own installation.
Requests, selected photos and relevant tool context can be sent to the external
assistant service when that integration is used; this is not a fully offline chat.

## Extension points

Add printer brands through `PrinterAdapter`, with transport and behavior tests.
Do not route another printer through U1 G-code. New generation workers should
retain originals, return provenance and validate geometry before library import.
New calibration tests must distinguish a geometric coupon from a true parameter
sweep, and provisional observations from physically confirmed results.
