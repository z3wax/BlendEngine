#!/usr/bin/env python3
"""Render real Cycles images, compare host output, and exercise persistent updates.
Requires numpy and OpenImageIO Python packages. Not a mocked renderer test.
"""
import argparse
import json
import pathlib
import select
import struct
import subprocess
import time
import numpy as np
import OpenImageIO as oiio

parser = argparse.ArgumentParser()
parser.add_argument('--bin-dir', type=pathlib.Path, required=True)
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
scene = pathlib.Path(__file__).with_name('reference.xml').resolve()
reference = args.output / 'reference.exr'
subprocess.run([str(args.bin_dir / 'cycles'), str(scene), '--background', '--dynamic-bvh', '--samples', '32',
                '--threads', '2', '--width', '96', '--height', '64', '--output', str(reference)], check=True,
               stdout=subprocess.DEVNULL, timeout=180)
process = subprocess.Popen([str(args.bin_dir / 'cycles_game_worker'), str(scene),
                            str(args.output), '96', '64', '32', '2'],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, bufsize=1)

def reply(prefix):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], 1)
        if not ready:
            if process.poll() is not None:
                raise AssertionError(process.stderr.read())
            continue
        line = process.stdout.readline().strip()
        if line.startswith(prefix):
            return line
        if line.startswith('ERROR'):
            raise AssertionError(line)
    raise TimeoutError(prefix)

def send(command, expect='FRAME'):
    process.stdin.write(command + '\n')
    process.stdin.flush()
    return reply(expect)

def pixels(revision):
    raw = (args.output / 'frame.rgba32f').read_bytes()
    w, h, rev = struct.unpack('<IIQ', raw[:16])
    assert (w, h, rev, len(raw)) == (96, 64, revision, 16 + 96*64*16)
    image = np.frombuffer(raw, dtype='<f4', offset=16).reshape(h, w, 4).copy()
    assert np.isfinite(image).all()
    return image

try:
    assert reply('READY') == 'READY 1 3'
    first_timing = send('render 1')
    first = pixels(1)
    preview = (args.output / 'preview.rgba32f').read_bytes()
    pw, ph, prev, sequence, completed_samples, reserved = struct.unpack('<IIQQII', preview[:32])
    assert (pw, ph, prev, reserved, len(preview)) == (96, 64, 1, 0, 32 + 96*64*16)
    assert sequence >= 1 and 0 < completed_samples <= 32
    source = oiio.ImageInput.open(str(reference))
    assert source
    original = source.read_image(format=oiio.FLOAT)
    source.close()
    error = float(np.abs(first - original).max())
    # CPU accumulation may differ by a few ULPs across scheduler order/ISA.
    assert np.allclose(first, original, atol=1e-6, rtol=1e-5), error
    second_timing = send('render 2')
    assert np.allclose(first, pixels(2), atol=1e-6, rtol=1e-5)
    send('render -1', 'ERROR')
    send('render 2', 'ERROR')  # Reject stale revisions without replacing a good frame.
    assert np.array_equal(first, pixels(2))
    send('object 0 0 0 0 0 0 0 0 0 0 0 0 0', 'ERROR')
    send('object 999 1 0 0 0 0 1 0 0 0 0 1 0', 'ERROR')
    send('object 0 1 0 0 0.5 0 1 0 0 0 0 1 0', 'UPDATED')
    send('render 3')
    assert float(np.abs(first - pixels(3)).max()) > 0.05
    send('object 0 1 0 0 0 0 1 0 0 0 0 1 0', 'UPDATED')
    send('render 4 1 0 0 0.4 0 1 0 0 0 0 1 0 0.85')
    assert float(np.abs(first - pixels(4)).max()) > 0.05
    send('render 5 1 0 0 0 0 1 0 0 0 0 1 0 0.85')
    assert np.allclose(first, pixels(5), atol=1e-6, rtol=1e-5)
    report = dict(status='PASS', max_absolute_error=error, width=96, height=64, samples=32,
                  first_frame=first_timing, reused_frame=second_timing,
                  checks=['reference_float32', 'progressive_float32', 'session_reuse', 'stale_revision',
                          'invalid_object', 'object_update', 'camera_update', 'restore'])
    (args.output / 'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
finally:
    if process.poll() is None:
        process.stdin.write('quit\n'); process.stdin.flush()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
    stderr = process.stderr.read()
    if stderr:
        print(stderr)
