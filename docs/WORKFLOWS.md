# PrintFlow workflows

[Back to the project overview](../README.md)

## Discover models and refine local designs

**Discover models** searches public listings across MakerWorld, Printables,
Thingiverse and other supported sources. Review a listing, select its original
files (including individual files in a ZIP), and import into Library with source,
author, available license and SHA-256. Some sources require downloading on their
own website; attach that download to its saved listing to retain provenance.
The search index is partial. Personal RSS search and an optional operator-managed
SearXNG backend are documented in [INSTALL.md](../INSTALL.md).

Local image reconstruction now isolates the subject, pads its foreground and
uses 256-resolution extraction by default. **Improve reconstruction** retains
originals and creates a new Library revision. This improves input handling and
mesh detail, but does not guarantee identity likeness or recover unseen geometry.
The interactive preview keeps whole facets; dense thumbnails are cached PNGs.

Chat model links, **Request complete** and the result card reopen the associated
Library model. Settings, colors, calibrated profiles and model info have separate
panels. Calibration begins with **Start with AI**, has evidence-based goal scores,
and keeps an immutable history of profile refinements.

## Calibration, colors and assembly plans

The chat displays actual activity, elapsed time and the last update. Quiet
requests are labeled as waiting, with no simulated percentage. Final responses
can recover after a host restart. `show_model` reveals a finished library model.

The model's **Colors** tab edits native 3MF slots in an immutable revision. An
STL has one uncolored mesh; semantic color regions require separate geometry.
Before printing, emitted G-code tools are checked against live material, nozzle
and reported color metadata. Material mismatches block printing; different colors
require explicit acceptance. Every new print requires a clear bed confirmation.

**Open original in Orca** preserves that file's saved settings. **Prepare model**
slices a copy with the selected settings. **Compare quality** creates alternative
jobs with real time/material estimates. Open a prepared job to review its actual
settings in Orca. **Start print** is separate: generating, opening and preparing
never start the printer.

**Calibration lab** ties tests to a printer, hotend and actual filament. Prepare
the original 3DBenchy comparison, review Jobs and explicitly start one when the
bed is clear. Completion of that exact test requests photos and measurements.
Photos are stored locally; Review photos with Codex sends the chosen evidence to
the connected account. AI visual interpretations remain provisional. Only
explicit physical benchmark feedback can verify a reusable profile. Photos do
not establish flow ratio, dimensions, strength or support removal effort.

Profiles save measured process settings, flow ratio, volumetric limits and
temperature. Experimental profiles can be benchmarked in their matching calibration session. Verified profiles
are matched by printer, hotend, material, brand/color, native filament profile and
firmware when reported, then ranked by purpose. Find them under Settings â†’
Calibrated profiles. Measured filament overrides currently apply to **single-slot
projects**; multicolor retains native per-slot profiles. Calibrate each material
separately. Temperature stays inside the native material range. Manual pressure
advance and retraction are observations, not automatic overrides.

Official U1 Dynamic Flow Calibration remains a printer operation; unloading
filament resets its K value. Special temperature/flow/PA sweeps remain native
Orca calibration operations. A plain tower mesh is not a parameter sweep, and
upstream Orca menus may differ from the installed Snapmaker fork.

**Assembly planner** cuts closed STL solids and unpainted native U1 3MF regions
into capped sections, checks volume conservation and assigns them to compatible
printers. One printer means sequential parts; several distribute the parts.
The grid fits the smallest selected build volume after margins and a multicolor
tower reserve. Orientation is retained. Numbered coordinates support assembly
of flat adhesive joints; automatic alignment pins, seam optimization and
structural certification are not implemented. Painted/texture facets and local
process overrides are rejected rather than discarded. Repair open meshes first.

U1 sections enter the existing native preparation workflow. Other printers can
have user-confirmed dimensions and single-color, AMS or independent-tool
capacities, but are **export-only** until their adapter exists. The ZIP contains
STL/standard color 3MF geometry and an assembly map, not machine-ready G-code.
Use the target printer's own slicer profile. Plans never auto-start consecutive
parts on an uncleared bed.

Persistent records use the existing data mount (`calibration.json`,
`assemblies.json`, `model-ready.json`). Photos, color revisions and assembly
outputs use the models mount and are excluded from Git. Update web/MCP, CAD and
Windows bridge together: the CAD worker needs Manifold and web/host need Pillow.
The original Benchy asset and provenance are in `models/calibration-assets`.

Primary guides reviewed October 24, 2026:
[Snapmaker U1 FAQ](https://wiki.snapmaker.com/en/FAQ/u1),
[Orca calibration](https://github.com/OrcaSlicer/OrcaSlicer/wiki/calibration_guide),
[Orca flow ratio](https://github.com/OrcaSlicer/OrcaSlicer/wiki/flow_ratio_calib),
[original 3DBenchy](https://www.3dbenchy.com/download/).

## Local model creation and previews

The Library shows STL and 3MF thumbnails, interactive geometry, dimensions,
object counts and configured material colors. STL has no stored print colors;
3MF palette counts may include configured colors that are not used by a plate.
Foreign 3MF projects must be saved with the native U1 preset before automation.
Selecting a model opens a large viewer with orbit, zoom and fit controls. Print
settings and model information use separate tabs beside the viewer, with the
preparation actions kept visible. Back to Library returns to the folder gallery.

Design studio generates boxes, spacers and modular display-table prototypes with
CadQuery. Dimensions are editable through new revisions; STL, STEP, parameters
and a regeneration source are retained. Selected printer dimensions constrain
the parts. Table joints include separate dowels and quantities; they need a fit
test and are not structurally certified. Material advice considers flexibility,
heat, outdoor exposure and loads without inventing loaded filament inventory.

The Roadster 2026 display template is an original approximation from published
reference photographs, not manufacturer CAD. Its wheels are fixed. It creates
three shared-origin color solids and a native U1 3MF with explicit part/tool
assignments. Select independent tools and three colors in trim, rear-lightbar,
body order. Closed-mesh checks and connected-solid checks run before import;
these checks do not establish visual fidelity or physical print quality.

The optional TripoSR worker reconstructs a model from a single object image,
then saves STL and a colored GLB reference to the local library. Its CPU path
completed a real development smoke test. Text-to-organic-figure generation,
semantic mesh editing and automatic four-tool color separation are not included.
Codex can create and revise the available parametric templates via the portal MCP.

Use Compare quality to run native U1 variants and inspect their actual time,
material, tools and effective settings. Progress stages are real workflow events;
they are not measured per-layer CLI progress.

The MCP's `print_quality_plan` provides dated sources and explicit candidate
settings. `compare_preparations` accepts two to four bounded variants; the
premium candidates compare 0.08 and 0.12 mm. `review_print_job` checks emitted
printer, tools and priming, while `tools/review_print_paths.py` audits linear
extrusion bounds and renders selected layers. Keep native temperatures, machine
limits and priming volumes unless actual evidence justifies a change. Same-PLA
supports must not inherit zero-gap settings intended for a different-material
interface. Research references are retained in `printflow/quality.py`.

## Preparing a print

1. Upload an STL or a native U1 3MF into a named folder.
2. For STL, select the real filament profile. For 3MF, preserve its existing
   material slots and painted colors.
3. Prepare at an appropriate layer height; enable supports only where needed.
4. Review actual emitted toolpaths, material/tool assignments and native 3MF.
5. Start the selected prepared job explicitly when the printer is available.

Better finish, easier support removal, speed and material savings are competing
objectives. Slicer estimates do not measure actual surface quality or support
removability. Test a representative piece and record physical feedback before
applying aggressive settings broadly. Full Spectrum painting remains a native
Orca workflow; the bridge preserves project content rather than generating that
painting automatically.

## Filament remaining

A printer reports loaded material and extrusion length, not the weight left on
an existing spool. Use **Set up tracking** on H1-H4 to register its current net
filament weight. A new 1 kg spool starts at 1000 g; a partly used spool needs its
current net weight, excluding the empty spool. Existing spools are never assumed
full automatically.

Usage is estimated as `length_mm * pi * (diameter_mm / 2)^2 * density / 1000`.
The dashboard marks remaining grams as approximate. Tool-change intervals can
only be split between sampled tools; those allocations are marked uncertain.
Use **Correct remaining weight** after weighing to reconcile the estimate.
Tracking starts at registration and does not reconstruct earlier consumption.

The camera and all printer functions use the official firmware already installed.
Community or extended firmware is not required or installed. Camera retries keep
the last successful frame visibly marked while a connection recovers.
