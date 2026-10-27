# Install PrintFlow Local

**New installation?** Follow [the step-by-step quick start](docs/GETTING_STARTED.md)
first, including [connecting Codex](docs/CODEX_SETUP.md). This guide covers advanced
host/container deployment, model workers, GPU prerequisites and troubleshooting.

- [Windows quick start](docs/GETTING_STARTED.md#1-check-the-requirements)
- [Connect the assistant and optional MCP client](docs/CODEX_SETUP.md)
- [How native slicing and calibration work](docs/SLICER_AND_CALIBRATION.md)

PrintFlow's source is open source. Web, portal MCP and CAD are separate Linux
containers. Image-to-3D is an optional fourth container. The native Snapmaker Orca
bridge runs on the Windows machine that has Orca and the signed-in Codex CLI.
Printer firmware is not modified. Docker Desktop is optional, not required.

## Windows host

Install Python 3.12+, official Snapmaker Orca with U1 profiles, and Codex CLI.
Sign in using `codex login`. From this source folder:

```powershell
.\install.ps1 -Mode Host
```

The host bridge uses port 8841 and a random token in `.runtime/bridge-token`.
The installer does not copy Codex credentials into a container. If an older native
PrintFlow process is already listening on 8841, stop it before changing its bind
mode. Keep the bridge reachable only from the local container environment.

For development without containers:

```powershell
.\install.ps1 -Mode Native -WithCad
```

This mode uses separate Python environments for the web/bridge and CAD. It does
not prove the container deployment or GPU runtime works.

### Start after a Windows restart

Add `-StartAtLogon` to the Windows installer to start this installation when the
current user signs in. For an existing native installation, run:

```powershell
.\tools\set-printflow-startup.ps1 -Mode Native
```

This creates a per-user Startup shortcut and starts only missing services in
hidden windows. It does not start or resume printing, change approval settings,
or run before sign-in. Use `-Mode Host` for the Windows bridge in a WSL container
deployment; start its Linux services in WSL separately. `-Mode Containers` uses
the existing Windows Docker command and requires its runtime to be available.
The source folder must stay at the registered path. Disable sign-in startup with:

```powershell
.\tools\set-printflow-startup.ps1 -Disable
```

To recover the native app immediately, run `.\tools\start-printflow.ps1` and open
`http://127.0.0.1:8840`. This does not restart services that are already listening.

## Open-source container runtime on Windows

Use Docker Engine inside Ubuntu 24.04 on WSL2. To request Ubuntu installation:

```powershell
.\install.ps1 -InstallWsl
```

Windows may require administrator access or a restart to enable WSL. Complete
Ubuntu's first-run account setup. Install Docker Engine and the Compose plugin
using the [official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/).
For a fresh Ubuntu runtime, `sudo sh tools/install-docker-ubuntu.sh` automates that
repository setup. It preserves existing installations and stops on package conflicts.
`sudo sh install.sh --install-runtime --image3d --gpu cpu --host-url URL` combines
the fresh runtime setup with PrintFlow installation.
No Windows driver, firmware or system component is silently replaced by PrintFlow.

Open this same checkout from WSL, for example:

```sh
cd '/mnt/c/Users/YOUR_NAME/Documents/ChatGPT/3D Print'
python3 tools/printflowctl.py doctor
sh install.sh --image3d --gpu cpu --host-url http://WINDOWS_HOST_IP:8841
python3 tools/printflowctl.py models
```

Replace `WINDOWS_HOST_IP` with the Windows address reachable from WSL. The default
gateway in `ip route` is commonly the Windows host in WSL NAT mode; verify the
address for your networking mode. `host.docker.internal` points at the Linux
Docker host when using Engine in WSL, so do not assume it reaches Windows.

The Windows bridge and containers must see the **same models directory**. The
simple deployment runs Compose from the Windows checkout through `/mnt/c`.
For a different physical server, provide an equivalent shared models directory
and a reachable authenticated Windows bridge. A Linux container alone does not
provide the Windows slicer GUI.

On native Linux filesystems, the data directories must be writable by UID 10001.
Run initialization as root if you want the installer to assign ownership:

```sh
sudo python3 tools/printflowctl.py init --image3d --gpu cpu --host-url http://WINDOWS_HOST_IP:8841
python3 tools/printflowctl.py up
```

The app is at `http://127.0.0.1:8840`; the portal MCP is at
`http://127.0.0.1:8842/mcp`. The CAD and image services have no published ports.
Ports are loopback-only by default. This is a local single-owner application,
not a public multi-user service.

For a nonstandard Orca installation, set `SNAPMAKER_ORCA_BIN` on the Windows host
before starting its bridge. Revalidate that binary with `tools/validate_bridge.py`.

## AMD RX 9070 XT

The installer distinguishes CPU, AMD native Linux and AMD WSL. Hardware detection
alone never marks acceleration as validated. Consult AMD's current
[Radeon WSL compatibility matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/wsl/wsl_compatibility.html)
and [ROCDXG instructions](https://github.com/ROCm/librocdxg).

After installing the supported official Windows AMD driver and WSL ROCm/ROCDXG
libraries, run from the WSL distribution hosting Docker Engine:

```sh
python3 tools/printflowctl.py init --image3d --gpu amd-wsl --host-url http://WINDOWS_HOST_IP:8841
python3 tools/printflowctl.py up
python3 tools/printflowctl.py models
python3 tools/printflowctl.py check-gpu
```

The WSL profile requires `/dev/dxg`, `libdxcore.so`, `librocdxg.so` and `dids.conf`.
Native AMD Linux uses `--gpu amd-linux` with `/dev/kfd`, `/dev/dri` and the video/
render group IDs. These paths are checked before selecting the profile. NVIDIA
and other GPU profiles are not yet supplied; CPU remains available.

`check-gpu` runs a tensor calculation inside the worker and identifies the device.
Only a completed image generation marks GPU inference as validated. The AMD image
tag is pinned to ROCm 7.2 / PyTorch 2.9.1; the container build and AMD runtime still
need testing on the target host. Do not upgrade drivers merely to match a label.

## Local design engines

The model viewer loads complete mesh buffers and reuses geometry for repeated
3MF instances. Its plate selector uses saved plate and instance assignments;
unassigned objects appear separately. Selecting a plate changes the preview,
not the original project or the scope of a preparation request. Standard 3MF
object/material colors are shown; painted facets and textures still need review
in Orca. Preview buffers are rebuildable caches under `.runtime/printflow/model-scenes`.
The scene budget is 256 MiB of unique GPU geometry; preparation is independent
of that viewing budget and still runs native project and slicer validation.
Large 3MF model parts are read incrementally into numeric arrays, without the
old 180 MB per-part XML limit or an in-memory XML node for every vertex and face.
NumPy writes the full GPU buffers in bounded batches. Library cards read only
small project metadata; opening a model triggers its geometry build. The viewer
shows the saved thumbnail during loading, reports transferred bytes and offers
**Retry preview** after a failed or stalled transfer. Geometry is reused when
switching plates. Old tabs receive an explicit reload instruction instead of
entering the retired JSON preview path.

- CadQuery generates editable boxes, spacers and modular display-table prototypes.
  Dimensions and STEP/source files are retained; edits create new revisions.
  The table template splits tops/legs to the selected build volume and supplies
  dowel parts. It is not structurally load-rated furniture.
- TripoSR reconstructs geometry from one isolated object image. Model weights are
  downloaded explicitly by `models`, pinned to a revision and SHA-256 checked.
  After setup the worker uses local weights and a local encoder configuration.
  It exports STL plus a colored GLB reference. Local U2Net background removal,
  subject cropping and foreground padding are applied before reconstruction.
  Transparent PNGs retain their alpha mask. Quality presets extract at 128
  (draft), 192 (balanced) or 256 (detail) resolution; detail is the default.
  Existing installations can add the background model with
  `python services/image3d/bootstrap.py background weights/triposr`.
  Install the updated `services/image3d/requirements.txt` in the image worker
  environment or rebuild its container. Generation never downloads weights
  implicitly. U2Net uses CPU inference; this does not validate AMD acceleration.
  Image revisions retain the source and original model. A single photograph
  cannot reliably recover hidden surfaces, cropped hair or exact facial likeness.
- TripoSR does not provide text-to-image, semantic part editing or automatic
  four-color separation. The current text-assisted editable route uses CadQuery
  templates through the MCP. More templates and model providers can be added.
- The U1 uses four independent tools. AMS and separately printed color parts are
  distinct modes. Planned colors still need verified slicer/material assignments.

The current web assistant uses the requested Codex account. That external account
service, Windows and the GPU driver retain their own licenses; they are not
converted into open-source services by containerizing PrintFlow.

The local foreground model is U2Net (Apache-2.0); TripoSR is MIT. The bootstrap
stores their provenance and license files alongside the weights. Provider model
files retain their own licenses. Do not describe the entire stack or all imported
models as MIT.

## Model discovery and imports

Discover models searches public web listings from MakerWorld, Printables,
Thingiverse, Cults, MyMiniFactory, Thangs and the original 3DBenchy site. Search
results are a partial index, not a synchronized copy of every provider's catalog.
Paste a model-page URL to read and save its public details. Direct STL/3MF/ZIP
links may be imported where the source exposes them. Account, payment, CAPTCHA
and blocked-access requirements stay on the source website: open the source,
download normally, then attach the file in its saved listing. No browser cookies
or third-party credentials are copied into PrintFlow.

Imports preserve original bytes, source URL, available author/license fields
and SHA-256. Unknown licensing remains unknown. ZIPs import only STL/3MF, reject
unsafe paths, and let you select up to 20 models per import from a package of up
to 250 MB expanded. G-code is excluded. Temporary ZIP selections expire after one hour.
Foreign printer projects retain their assignments and require native review in
Orca before U1 preparation. Importing does not print.

The default search adapter uses the host's connected Codex account and live web
search. It runs an ephemeral read-only search with shell, browser control, apps,
plugins and printer MCP servers disabled. Search text is sent to that account;
account usage limits apply. It does not join or interrupt the printer chat.
Text results are matched against URLs returned by the search tool. Image-search
events do not expose a structured result list in the current account protocol;
their source/image pairs are extracted from the search response and restricted
to supported model pages and that provider's own HTTPS image hosts. Thumbnails
load from their original CDN, with a clear unavailable state when blocked.
Load more excludes earlier model IDs (including alternate locale URLs) and
requests another page, up to eight pages. This is not provider catalog pagination.
Successful queries are cached for five minutes; service failures are not cached
as empty results. No catalog can be treated as complete.

For an operator-managed open-source search service, set `PRINTFLOW_SEARCH_URL`
to a SearXNG instance with JSON output enabled. The web service calls
`/search?format=json`; Compose passes this setting into the web container.
Search availability depends on the account or upstream engines. If unavailable,
the page offers a retry and direct searches on the selected source websites.
The marketplace shares the persistent Library/state volumes. The discovery
request uses `POST /api/marketplace/search` with the normal local request header.

## Guided calibration and revisions

Start with AI loads the actual printer/material context and existing sessions,
then asks the account-connected assistant to prepare or reuse the chosen test.
The test library contains 16 protocols, grouped by the problem they evaluate. Each explains its purpose, nominal dimensions,
reading procedure, limits and authoritative references. Account
tool approval restrictions can block assistant operations; the UI reports them
instead of claiming completion. The manual preparation/upload controls remain
available for explicit user actions.

Ten protocols can load a model and prepare comparison jobs directly: the
unchanged original 3DBenchy and nine original PrintFlow coupons. These cover
first-layer patches, overhangs from 35 to 75 degrees measured from vertical,
bridges with 10 to 50 mm clear spans, stringing, surface finish, fine features,
20 mm dimensions with known holes, diametral clearance and support removal.
Coupons are generated by the separate CadQuery service, validated and cached in
the persistent `models/calibration-assets/v1` directory. Viewing thumbnails does
not add every test to the Library; preparing or opening a model does.

Each comparison changes one variable: layer height by default, first-layer
infill speed for patches, bridge speed for bridges, outer wall speed for surface finish
and top support Z distance for the support coupon (0.16, 0.32 and 0.48 mm
at 0.16 mm layers). Its G-code must contain support extrusion before the job
can be offered for printing. Orca can round nominal gaps to layer positions. Overhang and bridge tests
stay unsupported; the support-removal coupon explicitly includes supports.
Native temperature, flow, retraction and pressure sweeps, plus official tool
alignment, remain native procedures. A plain tower STL is not a parameter sweep.
PrintFlow plans and records these procedures without changing printer firmware.

Each trial retains its recipe, model, variants, photos and observations. Select
Print variant to compare any ready variant; repeat preparation creates a new
trial without deleting earlier evidence. Photo review can target one trial.
Trial percentages count only its applicable goals confirmed by a human; they
are not physical accuracy or overall quality percentages.

Results show six specific goals: surface, stringing, bridges, first layer,
dimensions and support removal. Goals met is confirmed passes divided by all six;
coverage is assessed goals divided by six. Provisional photo impressions cannot
raise the confirmed score. Dimensions need measurements and support removal
needs a separate supported specimen. These percentages are not quality ratings.

Refine with AI creates a new session in the same profile family. Saving creates
an immutable revision with its own evidence. Experimental revisions can be
tested on a registered calibration coupon in a matching session, but cannot be applied
to unrelated models until physically verified. Earlier settings and evidence
remain available. Only official firmware is supported.

Once a test is ready, its print action opens a prepared baseline with
the session's printer and hotend selected. Confirm the clear build plate there
and press **Start print**. The server checks live material/nozzle identity again
before uploading. Preparation, submission, live printing and completion are
separate states; preparing or viewing calibration never starts a print.

The model workspace uses WebGL depth testing to display overlapping surfaces
correctly. Enable graphics acceleration if WebGL is unavailable, or open the
original in Orca. Cached generated thumbnails use a software depth buffer.
Neither preview path changes the source STL or 3MF.

## Codex action permissions

PrintFlow keeps approval prompts off by default. An action that needs permission
can be rejected in that mode. At the top of the chat, find **Action permissions** and
choose **Enable prompts** to let Codex ask for a decision on future
requests. This setting does not replay a rejected action, grant permission or
start a print. Send a new preparation request after enabling it. The current
request must finish before changing this setting.

Command and file requests offer one-time decisions. Tool questions show the
exact choices supplied by Codex, with no answer preselected. Unsupported request
types fail closed. Managed restrictions can still reject an action; enabling
prompts does not override them. The preference is stored in the persistent data
directory as `codex-preferences.json`. Physical printing still requires its own
explicit action and current build-plate and material checks.

Pending approval cards follow a versioned server snapshot. Resolved or expired
requests are removed; old browser responses cannot approve a later request that
reuses a runtime ID. Reload the page after an update to load the current client.

## Preparation responsiveness

The AI receives compact printer and job summaries. `farm_status(details=true)`
retains access to raw diagnostics; `job_status` returns complete emitted settings,
errors and comparison variants. Use `job_status(job_id, wait_seconds=20)` for an
active preparation instead of repeated immediate status calls. The direct
`GET /api/jobs/{job_id}` endpoint supports a bounded wait of 0â€“25 seconds and
does not depend on the dashboard's recent-job limit.

Native slicing preserves the placement saved in the project (`--arrange 0`).
Orca's normal collision checks still apply. If a layout does not fit, revise a
copy before slicing; the bridge does not silently rearrange parts or remove the
native prime tower. Preview memory limits do not block native preparation.

## Model-aware preparation and print images

The chat displays its selected Codex model and reasoning effort. PrintFlow stores
these choices in `codex-preferences.json` and explicitly sends them with each new
turn. The host validates them against the signed-in account's model catalog;
global Codex settings are unchanged. Higher reasoning effort can take longer.

`preparation_guide` exposes the linked OrcaSlicer and Snapmaker guidance used by
the assistant. Adaptive `prepare_job` and `compare_preparations` inspect contact,
downward faces and saved overrides. For STL they rank candidate orientations
and propose brim, support type and layer height using local geometric heuristics.
Functional/fit parts preserve orientation until their load and mating surfaces
are understood. Native 3MFs retain their authored plate layout, painting and
material assignments. This is not automatic optimization of every slicer setting.
Material temperature, flow, cooling, motion and priming retain compatible native
or measured profile values; physical finish still needs a real test.

In **Jobs**, choose **Print image** to see top and angled views of emitted
extrusion paths. The print setup dialog also links this image. Select a prepared
plate when a job contains several. Model paths use saved G-code filament colors;
supports, brim/skirt and the prime tower use the image's legend colors. Physical
hotend remapping may change the loaded colors, which are checked separately at
print setup. The image is a schematic, not a prediction of surface finish.

Images are generated on demand, cached by G-code revision, and contain all
supported extrusion segments within a bounded budget. An 82 MB development
example took about 16 seconds to render cold; cached responses avoid that work.
Unsupported arc formats or budgets produce an explicit error, not a partial
image. Firmware macros and travel paths are omitted. The labeled object count
comes from `EXCLUDE_OBJECT_DEFINE`: a merged object cannot be skipped by
individual piece, even if its mesh contains disconnected parts.
