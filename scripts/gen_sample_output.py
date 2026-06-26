"""Generate sample_output.json by running every public sample case through the
service's pure analyze() function. Produces a required submission deliverable."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import analyze  # noqa: E402
from app.schemas import TicketRequest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

with open(os.path.join(ROOT, "tests", "sample_cases.json"), encoding="utf-8") as fh:
    cases = json.load(fh)["cases"]

results = []
for case in cases:
    req = TicketRequest(**case["input"])
    out = analyze(req)
    results.append({"id": case["id"], "input": case["input"],
                    "output": out.model_dump()})

with open(os.path.join(ROOT, "sample_output.json"), "w", encoding="utf-8") as fh:
    json.dump({"generated_by": "QueueStorm Investigator", "results": results},
              fh, ensure_ascii=False, indent=2)

print(f"Wrote sample_output.json with {len(results)} cases.")
