# Contributing

Thanks for helping improve PrintFlow Local. Keep code, public documentation,
interface text and error messages in English.

## Set up a development checkout

Use Python 3.12+ and Node.js 22+. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
.\.venv\Scripts\python.exe -m pip install -e 'vendor/snapmaker-u1-mcp[test]'
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
node --test tests/*.test.cjs
```

On Linux, use `.venv/bin/python` instead of `.venv/Scripts/python.exe`.
These tests use isolated fixtures and mocked printer operations. They do not
require Orca, credentials, a GPU or a live printer. Some CAD tests are skipped
outside the separate CAD environment.

If Windows denies access to an old pytest temporary directory, use a fresh
directory with `--basetemp .runtime/pytest-UNIQUE_NAME`. Never reuse a directory
that contains files you want to keep: pytest owns its base temporary directory.

## CAD checks

```powershell
python -m venv .venv-design
.\.venv-design\Scripts\python.exe -m pip install -r requirements-design.txt
.\.venv-design\Scripts\python.exe -m unittest discover -s tests -p test_calibration_geometry.py
.\.venv-design\Scripts\python.exe -m tests.verify_assembly_geometry
```

CAD tests verify mesh geometry and volume; they do not establish fit or strength.
Run source packaging with `.venv/Scripts/python.exe tools/package-source.py`.
Only allowlisted source and the attributed benchmark belong in that archive.

## Optional GitHub Actions

`deploy/github-actions-tests.example.yml` is a ready-to-use workflow template
for Python and JavaScript unit tests on Windows and Linux, plus source packaging.
Copy it to `.github/workflows/tests.yml` to enable it in your repository. Publishing
an active workflow requires GitHub's workflow write permission in addition to
repository contents write permission. The template itself does not run Actions.

## Native and physical checks

`tools/validate_bridge.py` runs real Snapmaker Orca comparisons on Windows and
records the installed executable hash. Run it after changing the native bridge
or updating Orca. It creates local output but does not send printer commands.

Live printer tests require a separate, explicit physical workflow. Never interrupt
an existing print for an integration test. Use official firmware and confirmed
material, nozzle and tool assignments. Record physical outcomes only when
observed; successful slicing does not prove finish or support removability.

## Submit a change

1. Describe the concrete issue and intended behavior.
2. Keep edits focused and preserve originals for model/project revisions.
3. Add meaningful regression coverage for changed behavior and run relevant tests.
4. For visual changes, check desktop and narrow layouts, dark/light themes and
   panel scrolling. Do not claim visual verification from source tests alone.
5. Explain verification and remaining limitations in the pull request.

Do not commit models from your library, account information, LAN addresses,
conversations, photos, generated G-code, `.env`, runtime folders or backups.
Use minimal synthetic fixtures. Preserve third-party notices when updating
vendored code and record the upstream revision in `THIRD_PARTY.md`.

Preparation settings should follow the actual model and native material profile.
Keep painting, tools and native priming intact; avoid universal brim/support
presets. Calibration percentages must represent recorded checks, not invented
quality scores. Keep the host, worker and printer boundaries explicit.
