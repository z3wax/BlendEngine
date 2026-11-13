#!/usr/bin/env python3
"""Verify geometry sharing preserves render output, authored normals and UV tangents."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import numpy as np
import OpenImageIO as oiio

p = argparse.ArgumentParser()
p.add_argument('--bin-dir', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
base = ET.parse(Path(__file__).with_name('reference.xml')).getroot()
source_state = base.find('state')
mesh = source_state.find('mesh')
mesh.set('N', '0 0 -1 0 0 -1 0 0 -1')
mesh.set('UV', '0 0 0.5 1 1 0')
mesh.set('T', '1 0 0 1 0 0 1 0 0')
mesh.set('TS', '-1 -1 -1')
source_state.set('smooth', 'true')
# A connected normal map exercises the exported tangent frame.
shader = base.find('shader')
ET.SubElement(shader, 'normal_map', name='normal', color='0.6 0.5 0.98', strength='0.7')
ET.SubElement(shader, 'connect', {'from': 'normal normal', 'to': 'p normal'})
results = {}
for mode in ['shared', 'expanded']:
    root = copy.deepcopy(base)
    transform = ET.SubElement(root, 'transform', translate='1.2 0 0.4')
    if mode == 'shared':
        ET.SubElement(transform, 'instance', object='0')
    else:
        transform.append(copy.deepcopy(source_state))
    scene = a.output / f'{mode}.xml'
    image = a.output / f'{mode}.exr'
    ET.ElementTree(root).write(scene)
    subprocess.run([str(a.bin_dir / 'cycles'), str(scene), '--background', '--quiet',
                    '--dynamic-bvh', '--width', '96', '--height', '64', '--samples', '64',
                    '--threads', '2', '--output', str(image)], check=True, timeout=180)
    source = oiio.ImageInput.open(str(image))
    results[mode] = source.read_image(format=oiio.FLOAT)
    source.close()
error = float(np.abs(results['shared'] - results['expanded']).max())
assert np.allclose(results['shared'], results['expanded'], rtol=1e-5, atol=1e-6), error
report = {'status': 'PASS', 'max_absolute_error': error,
          'checks': ['shared_geometry_vs_duplicate', 'authored_normals', 'normal_map_tangents']}
(a.output / 'instancing-verification.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
