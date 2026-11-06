# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the native game and real physics scenarios inside iOS Simulator."""
import json
from pathlib import Path
import signal
import subprocess
import time


def command(*words, timeout=120, check=True):
    result = subprocess.run(['xcrun', 'simctl', *map(str, words)], capture_output=True,
                            text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError('simctl %s failed: %s' % (words[0], result.stderr[-2000:]))
    return result.stdout


def _available_simulator():
    runtimes = json.loads(command('list', 'runtimes', '-j'))['runtimes']
    runtimes = [r for r in runtimes if r.get('isAvailable') and '.iOS-' in r['identifier']]
    if not runtimes:
        raise RuntimeError('No available iOS Simulator runtime is installed')
    runtime = max(runtimes, key=lambda r: tuple(int(v) for v in r['version'].split('.')))
    types = json.loads(command('list', 'devicetypes', '-j'))['devicetypes']
    phones = [t for t in types if t.get('productFamily') == 'iPhone']
    preferred = next((t for t in phones if t['name'] == 'iPhone 16 Pro'), None)
    phone = preferred or next((t for t in reversed(phones) if 'Pro' in t['name']), phones[-1])
    udid = command('create', 'BlendEngine native IPA QA', phone['identifier'], runtime['identifier']).strip()
    return udid, runtime['name'], phone['name']


def test_game(app, bundle, proof):
    proof = Path(proof)
    report = {'passed': False, 'physical_device_tested': False, 'touch_tested': False,
              'normal_launcher': False, 'unsigned_device_ipa_install_tested': False}
    udid, runtime, device = _available_simulator()
    report.update(simulator=udid, runtime=runtime, device=device)
    processes = []
    recording = None
    handles = []

    def launch(label, args=()):
        log = proof / (label + '.log')
        stream = log.open('w')
        handles.append(stream)
        proc = subprocess.Popen(['xcrun', 'simctl', 'launch', '--terminate-running-process',
            '--console', udid, bundle, *args], stdout=stream, stderr=subprocess.STDOUT)
        processes.append(proc)
        return proc, log

    def state():
        try:
            return json.loads((data / 'Documents/qa_state.json').read_text())
        except (OSError, ValueError):
            return None

    def await_state(predicate, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = state()
            if value and predicate(value):
                return value
            time.sleep(1)
        raise RuntimeError('iOS native state timeout: ' + str(state()))

    def await_marker(proc, log, marker, timeout=240):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            content = log.read_text(errors='replace') if log.exists() else ''
            if 'SCRIPT ERROR:' in content or 'LAST_SIGNAL_SMOKE_FAIL' in content or 'LAST_SIGNAL_AGENT_FAIL' in content:
                raise RuntimeError('Native simulator scenario failed; inspect ' + log.name)
            if marker in content:
                # UIKit can keep the process alive after SceneTree.quit().
                # The explicit PASS marker is the completed scenario boundary;
                # a still-running application is terminated only as teardown.
                if proc.poll() is not None and proc.returncode:
                    raise RuntimeError('Simulator exited nonzero after ' + marker)
                if proc.poll() is None:
                    command('terminate', udid, bundle, check=False)
                    proc.wait(timeout=30)
                return content
            if proc.poll() is not None:
                raise RuntimeError('Simulator game exited before ' + marker + ': ' + content[-2000:])
            time.sleep(1)
        raise RuntimeError('Simulator scenario timed out: ' + marker)

    try:
        command('boot', udid)
        subprocess.run(['open', '-a', 'Simulator', '--args', '-CurrentDeviceUDID', udid], check=True)
        command('bootstatus', udid, '-b', timeout=240)
        command('install', udid, app, timeout=120)
        data = Path(command('get_app_container', udid, bundle, 'data').strip())
        report['data_container_verified'] = data.is_dir()
        recording = subprocess.Popen(['xcrun', 'simctl', 'io', udid, 'recordVideo',
            '--codec=h264', str(proof/'iOS-native-gameplay.mp4')], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        proc, log = launch('normal-launch')
        normal = await_state(lambda s: s.get('native') and s.get('floor')
            and s.get('event') == 'playing' and len(s.get('npc_agents', [])) == 1
            and s['npc_agents'][0].get('walked', 0) > .2
            and s['npc_agents'][0].get('walk_pose_changes', 0) > 0)
        report['normal_launcher'] = True
        report['native_normal_state'] = normal
        if proc.poll() is not None:
            raise RuntimeError('Normal native game exited before screenshot capture')
        if normal.get('clues') != 0 or normal.get('walked', 0) > .1:
            raise RuntimeError('Guide must not collect clues or move the idle player')
        command('io', udid, 'screenshot', proof/'iOS-native-scene.png')
        time.sleep(3)
        if proc.poll() is not None:
            raise RuntimeError('Normal native game exited during capture')
        recording.send_signal(signal.SIGINT)
        recording.wait(timeout=30)
        recording = None
        command('terminate', udid, bundle)
        proc.wait(timeout=30)

        proc, log = launch('full-story', ['--audio-driver', 'Dummy', '--', '--smoke-test'])
        await_marker(proc, log, 'LAST_SIGNAL_SMOKE_PASS')
        final = state()
        if not (final and final.get('state') == 'WON' and final.get('floor')
                and final.get('clues') == 5 and final.get('jumps', 0) >= 3
                and final.get('walked', 0) >= 25):
            raise RuntimeError('Missing grounded five-clue story completion evidence')
        agents = final.get('npc_agents', [])
        if not (len(agents) == 1 and agents[0].get('state') == 'IDLE'
                and agents[0].get('walked', 0) > 1
                and agents[0].get('walk_pose_changes', 0) > 0):
            raise RuntimeError('Missing independent NPC story movement/animation')
        report['native_smoke'] = final
        proc, log = launch('npc-physics', ['--audio-driver', 'Dummy', '--script', 'res://tests/agent_smoke.gd'])
        text = await_marker(proc, log, 'LAST_SIGNAL_AGENT_PASS')
        line = next(line for line in text.splitlines() if 'LAST_SIGNAL_AGENT_REPORT ' in line)
        npc = json.loads(line.split('LAST_SIGNAL_AGENT_REPORT ', 1)[1])
        if not npc.get('passed'):
            raise RuntimeError('NPC physics report did not pass')
        report['npc_physics'] = npc
        report['passed'] = True
        report['notes'] = ('Native iOS Simulator app used the same source/assets as the device build. '
            'The unsigned physical-device IPA is structurally verified, not installed. '
            'No physical iPhone or synthetic UIKit touch automation was used.')
        return report
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        if recording and recording.poll() is None:
            recording.send_signal(signal.SIGINT)
            try:
                recording.wait(timeout=20)
            except subprocess.TimeoutExpired:
                recording.kill()
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for stream in handles:
            stream.close()
        (proof/'simulator_qa.json').write_text(json.dumps(report, indent=2)+'\n')
        command('shutdown', udid, check=False)
        command('delete', udid, check=False)
