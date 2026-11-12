#!/usr/bin/env python3
"""Package reviewable native source, Blender files and original licenses."""
from pathlib import Path
import zipfile,hashlib
root=Path(__file__).resolve().parents[2];out=root/'dist/z3wax';out.mkdir(parents=True,exist_ok=True)
files=[]
for folder in ['native/z3wax','tools/z3wax','tools/android','tools/ios','docs/z3wax']:
 files.extend(p for p in (root/folder).rglob('*') if p.is_file() and not any(x in p.parts for x in ['.godot','__pycache__','build']) and p.suffix not in ['.import','.pyc'])
files += [root/'builds/Z3WAX/character.blend',root/'builds/Z3WAX/disland_outpost.blend',root/'COPYING']
p=out/'Z3WAX-0.1.0-source.zip'
with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
 for f in sorted(files):z.write(f,f.relative_to(root))
print(p,hashlib.sha256(p.read_bytes()).hexdigest())
