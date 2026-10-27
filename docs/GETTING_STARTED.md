# Install PrintFlow and prepare your first model

[Project overview](../README.md) · [Connect Codex](CODEX_SETUP.md) · [Advanced installation](../INSTALL.md)

This walkthrough uses a Windows host with native Snapmaker Orca and separate
Python environments. It is the shortest route to a working local workspace.
For Docker Engine in WSL2, CPU image reconstruction or AMD prerequisites, continue
with the [deployment guide](../INSTALL.md).

## 1. Check the requirements

| Component | Required for |
| --- | --- |
| Windows host with Python 3.12+ | Portal, native bridge and local service tools. `python --version` must work. |
| Git | Cloning this repository. GitHub's **Code → Download ZIP** is an alternative. |
| Official Snapmaker Orca with U1 presets | Preparing and comparing native U1 projects. |
| Codex CLI, signed in on that Windows account | The assistant in PrintFlow. See [Codex setup](CODEX_SETUP.md). |
| Modern browser with WebGL | Interactive model previews. Use a current Chrome, Edge or compatible Chromium browser. |
| U1 reachable over the LAN | Live printer monitoring and explicit printing. Use official firmware. |
| CAD worker | Parametric design and calibration coupon generation; installed by `-WithCad`. |
| Optional image worker and downloaded weights | Local image-to-3D. CPU is supported; GPU acceleration needs separate validation. |

Node.js is not a frontend build dependency. It is needed if you choose the npm
installation of Codex, and Node.js 22+ runs this project's JavaScript tests.
There is no measured universal RAM/VRAM minimum: geometry size, image resolution
and the chosen worker determine memory use. Leave disk space for Python
environments, model weights, original models and generated slicing jobs.

## 2. Get the source

Open PowerShell in the folder where you want to keep PrintFlow:

```powershell
git clone https://github.com/dliratx/printflow-local.git
cd printflow-local
```

If you downloaded the ZIP, extract it first and open PowerShell in the extracted
folder. Keep the source at a stable path if you later enable startup at sign-in.

## 3. Install and sign in to Codex

Follow [Connect Codex](CODEX_SETUP.md) on this same Windows account, then check:

```powershell
codex --version
codex login status
```

Complete sign-in before starting PrintFlow. Your account credentials remain with
Codex on the host; do not put them in this repository, `.env` or a container.

## 4. Install PrintFlow

```powershell
.\install.ps1 -Mode Native -WithCad
```

The installer creates `.venv` for the web/host/MCP services and `.venv-design`
for CAD, installs dependencies and starts the local services. It does not include
Snapmaker Orca, GPU drivers or image-model weights. If an organization's policy
blocks a script, follow its approved script-running process; do not disable
managed protections to install PrintFlow.

Open **http://127.0.0.1:8840**. The regular native services are:

| Port | Service |
| --- | --- |
| 8840 | Web workspace |
| 8841 | Authenticated Windows bridge |
| 8842 | Portal MCP, `/mcp` |
| 8843 | CAD worker |
| 8844 | Optional image-to-3D worker |

## 5. Validate Snapmaker Orca

Install the official application with its U1 profiles. The default Windows path
is `C:\Program Files\Snapmaker_Orca\snapmaker-orca.exe`.

```powershell
.\.venv\Scripts\python.exe tools\validate_bridge.py
```

The check creates synthetic fixtures, runs real native slicing comparisons and
records the executable hash. It does not send printer commands. Repeat it after
updating Orca. A missing preset, wrong installation path or changed executable
must be resolved before relying on preparation results.

## 6. Connect a printer and the assistant

1. In PrintFlow, choose **Add printer** and enter its name and LAN address.
2. Confirm that the dashboard reports the correct device and loaded materials.
3. Open **Codex**. Check that the account is connected and a model is shown.
4. Use a first request such as: “List my library and available design tools.”
5. Follow [Codex setup](CODEX_SETUP.md#verify-the-connection) if the connection is
   missing. Registration alone does not prove an MCP connection works.

The integrated assistant attaches the local portal MCP to its conversation.
Manual CLI registration is optional and documented separately.

## 7. Explore the model workflow

![Model library](screenshots/library.jpg)

Upload an STL or 3MF into **Library**. Select it to inspect dimensions, geometry,
plates and configured colors. STL has no stored filament assignments. A native
U1 3MF can retain its existing material slots and object colors.

**Design studio** creates supported parametric templates and saves revisions.
**Design with Codex** adds your design context to a chat draft; review and send
it. The optional **Image to 3D** route needs its local worker and model weights.
It is a reconstruction workflow, with different editing capabilities from CAD.

## 8. Prepare, inspect and explicitly print

1. Select the actual material or review the 3MF's existing slots.
2. Prepare a model or ask the assistant for a comparison of purposeful variants.
3. In **Jobs**, inspect time/material estimates, emitted settings and **Print image**.
4. Open the prepared 3MF in Orca if you need to review the native project.
5. When ready, explicitly choose **Print**, validate tool mapping and confirm the
   plate is clear for that job.

Opening a project, creating a model or finishing a slice does not start a print.
See [how the slicer MCP works](SLICER_AND_CALIBRATION.md) for tuning and calibration.

## Start again, update and recover

```powershell
.\tools\start-printflow.ps1
```

To enable startup for this installation when the current user signs in:

```powershell
.\tools\set-printflow-startup.ps1 -Mode Native
```

For backups and updates, follow [Maintenance](../MAINTENANCE.md). Keep `.env`,
`.runtime`, `models`, `runs` and backups private. A source ZIP is not a data backup.
