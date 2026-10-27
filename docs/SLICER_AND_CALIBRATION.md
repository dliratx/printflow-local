# How the slicer MCP and calibration work

[Project overview](../README.md) · [Installation](GETTING_STARTED.md) · [Connect Codex](CODEX_SETUP.md)

PrintFlow gives the assistant tools that operate on **real saved projects and
the native Snapmaker Orca slicing engine**. The assistant can prepare jobs on
your behalf: inspect a model, propose supported changes, run comparisons and
return projects, toolpaths and estimates for review.

## Two MCP boundaries

| Component | Responsibility |
| --- | --- |
| **PrintFlow portal MCP** | Library, local generation, preparation jobs, calibration records, profile recommendations and explicit printer actions. Runs as its own service/container. |
| **Native U1 slicer MCP / Windows bridge** | Saved STL/3MF inspection, native profiles, bounded setting changes, Orca CLI slicing and emitted G-code analysis. Stays on the Windows host. |

The assistant works through these tools instead of requiring you to edit each
supported slicer setting manually. Its control is the native CLI and saved-file
workflow: it can open a project in Orca, but does not synchronize unsaved GUI
edits or automate every control in Orca's window.

## From a model to a tuned candidate

1. **Establish the actual setup.** Read printing preferences, confirm printer,
   nozzle, plate and loaded filament. A material recommendation is not inventory.
2. **Inspect the source.** Examine dimensions, placement, contact area, overhangs,
   native 3MF slots, object colors, plates and local overrides. STL orientation
   candidates and saved 3MF placement are distinct inputs.
3. **Choose deliberate changes.** Discuss visible faces, fit, load and support
   access. Propose orientation before adding supports. Use a brim where adhesion
   risk justifies it; model brim, support bases and prime-tower brim differ.
4. **Compare two to four alternatives.** For example, compare appropriate layer
   heights or support contact gaps. Keep matching native material, machine and
   tool-priming settings unless measured evidence supports a change.
5. **Run Snapmaker Orca.** Slice project copies through the installed native CLI.
   Preserve originals, painting and tool assignments. Validate the installed
   executable again after an Orca update.
6. **Review what was emitted.** Check printer identity, actual tools, extrusion
   features, supports, tower, effective settings and time/gram estimates.
7. **Choose a result and inspect its image.** Review the prepared project or its
   actual sliced paths before explicitly starting a print.

Supported settings are bounded by the bridge's validated allowlist. The project
does not tune every hidden native option, guarantee an optimum angle, or measure
physical quality from a geometric score. Candidate reasoning and guide sources
are maintained in [`print_strategy.py`](../printflow/print_strategy.py) and
[`quality.py`](../printflow/quality.py). Routine jobs use that dated guidance;
new research is appropriate when requested or when materials/software change.

## Understand the buttons

| Action | What happens |
| --- | --- |
| **Open original** | Sends that saved file to Orca with its existing settings. It does not apply a new recommendation. |
| **Prepare model** | Applies selected supported settings to a review copy and runs native slicing. |
| **Compare quality** | Runs purposeful variants and reports actual slicer estimates. The comparison is not a physical quality score. |
| **Open in Orca** on a prepared job | Opens that job's prepared native project for inspection. Unsaved GUI edits must be saved before file-based tools can inspect them. |
| **Print image** | Shows top and angled views of emitted extrusion paths, including supports and adhesion structures. |
| **Print** | Separate printer action with current material/tool validation and fresh clear-bed confirmation. |

![Actual emitted path preview](screenshots/sliced-print-preview.jpg)

*This support-test example comes from a real saved native slice. It is a schematic
of paths and placement, not a photograph or simulation of the finished surface.*

## Calibration is a loop

**Prepare → explicitly print → observe → record → save a revision → test again.**

Start with a session tied to the printer, hotend and actual filament. AI can
help choose and prepare the right benchmark; the original 3DBenchy is an overall
baseline. Focused coupons isolate a problem more effectively than repeatedly
printing unrelated models.

![Categorized calibration catalog](screenshots/calibration-tests.jpg)

| Test family | What you evaluate |
| --- | --- |
| Original 3DBenchy | Repeatable overall comparison, details, hull surfaces and bridges; original scale, no supports. |
| First-layer patches | Adhesion and line consistency at several bed positions. |
| Overhang ladder | Unsupported underside quality at increasing angles. |
| Bridge ladder | Unsupported horizontal spans between anchors. |
| Stringing / surface / fine features | Strings, ringing, top skin and whether small walls/pins survive printing. |
| Dimension / clearance gauges | Measured size and actual assembly fit; use calipers and physical trials. |
| Support-release coupon | Removal effort and supported underside finish at different contact gaps. |
| Native temperature / flow / retraction / PA tests | Controlled parameter sweeps or official printer procedures; a plain mesh is not a sweep. |
| Multi-tool alignment | Registration using the supported official U1 procedure. |

After the exact test finishes, add front, side, rear and underside photos where
appropriate, plus measurements and your removal/fit observations. Selected
photos can be reviewed with Codex; that shares the selected evidence with the
external account service. Visual interpretations remain provisional.

The displayed percentage is **confirmed passed checklist goals / all goals**.
Coverage tracks how many goals have been assessed. Unmeasured goals stay pending.
This percentage is not a certification of overall print quality.

## Save a profile and keep refining it

Profiles retain context and an immutable revision history. Compatible verified
profiles are matched to printer, hotend, material, native filament profile,
brand/color and reported firmware context, then ranked for the intended purpose.
An experimental revision can be tested again in its matching calibration session.
New results refine the same profile lineage while preserving previous revisions.

Measured process, temperature, flow-ratio and volumetric-flow limits can be reused
within the supported bounds. Current measured filament overrides apply to
**single-slot projects**; multicolor keeps native per-slot profiles. Calibrate
each material/tool combination instead of assigning one universal profile.
Manual pressure-advance and retraction values remain observations rather than
automatic overrides in this release.

Official U1 dynamic-flow calibration stays a printer operation. Support-interface
materials require confirmed compatible loaded spools and a physical test. Finish,
strength, adhesion and easy support removal cannot be promised from slicing alone.

See [detailed workflows](WORKFLOWS.md) for colors, assembly planning and profile
matching, and [Maintenance](../MAINTENANCE.md) for safe update/revalidation steps.
