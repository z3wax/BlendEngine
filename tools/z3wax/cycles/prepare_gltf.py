#!/usr/bin/env python3
"""Resolve Godot visibility before importing a glTF snapshot with Blender 4.3.
Hidden nodes are disconnected according to KHR_node_visibility, not shown by
silently dropping the extension. The original source file is never overwritten.
"""
import argparse
import json
from pathlib import Path
import struct

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
assert args.source.resolve() != args.output.resolve()
raw = args.source.read_bytes()
magic, version, size = struct.unpack_from('<III', raw)
assert magic == 0x46546C67 and version == 2 and size == len(raw)
length, kind = struct.unpack_from('<II', raw, 12)
assert kind == 0x4E4F534A
document = json.loads(raw[20:20 + length])
hidden = {i for i, node in enumerate(document.get('nodes', []))
          if node.get('extensions', {}).get('KHR_node_visibility', {}).get('visible') is False}
for node in document.get('nodes', []):
    node.get('extensions', {}).pop('KHR_node_visibility', None)
    if 'children' in node:
        node['children'] = [i for i in node['children'] if i not in hidden]
for scene in document['scenes']:
    scene['nodes'] = [i for i in scene['nodes'] if i not in hidden]
for key in ['extensionsRequired', 'extensionsUsed']:
    document[key] = [item for item in document.get(key, []) if item != 'KHR_node_visibility']
payload = json.dumps(document, separators=(',', ':')).encode()
payload += b' ' * (-len(payload) % 4)
rest = raw[20 + length:]
args.output.write_bytes(struct.pack('<III', magic, version, 20 + len(payload) + len(rest)) +
                        struct.pack('<II', len(payload), kind) + payload + rest)
print(f'Prepared snapshot; resolved {len(hidden)} hidden nodes')
