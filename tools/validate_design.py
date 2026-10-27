"""Real CAD contract smoke test. Run with the design worker's Python environment."""
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cadquery as cq
from printflow.design_geometry import generate
from printflow.design_schema import validate_request, U1


def main():
    printer = {"id": "validation", "name": "U1 validation", **U1}
    with tempfile.TemporaryDirectory() as temp:
        summary = []
        for template, parameters in [("box", {}), ("spacer", {}), ("table", {"width": 400, "depth": 300, "height": 350})]:
            destination = Path(temp) / template
            request = validate_request({"template": template, "parameters": parameters}, printer)
            result = generate(request, destination)
            assert all(all(0 < d <= 258.01 for d in part["dimensions"]) for part in result["parts"])
            solid = cq.importers.importStep(str(destination / "model.step")).val()
            assert solid.isValid() and solid.Volume() > 0
            if template == "box":
                expected = 100*70*40 - 96*66*38
                assert abs(solid.Volume()-expected) < .01
            if template == "table":
                assert len([p for p in result["parts"] if p["name"].startswith("top_") and p["name"].split("_")[1].isdigit()]) == 4
                assert sum(p["quantity"] for p in result["parts"]) == 28
            summary.append({"template": template, "unique_parts": len(result["parts"]), "valid_step": True})
        print(json.dumps(summary))


if __name__ == "__main__": main()
