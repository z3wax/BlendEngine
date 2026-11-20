"""Download pinned, credited artist inputs; reject any content hash mismatch."""
from pathlib import Path
import hashlib
import json
import sys
import urllib.request

if len(sys.argv) != 2:
    raise SystemExit("Usage: python fetch_sources.py OUTPUT_DIRECTORY")
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
manifest = json.loads(Path(__file__).with_name("source_inputs.json").read_text())
for item in manifest:
    target = output / item["file"]
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"]:
        print("Verified", target.name)
        continue
    request = urllib.request.Request(item["url"], headers={"User-Agent": "Z3WAX-art-pipeline/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise SystemExit("Source hash mismatch: " + item["file"])
    target.write_bytes(data)
    print("Downloaded and verified", target.name)
