"""Build the self-contained executive dashboard (dashboard/index.html) from exports/kpis.json."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / "exports" / "kpis.json").read_text())
html = (Path(__file__).parent / "template.html").read_text().replace("__DATA__", json.dumps(data))
(Path(__file__).parent / "index.html").write_text(html)
print("dashboard/index.html written", f"({len(html) // 1024} KB)")
