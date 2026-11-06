# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the native game and real physics scenarios inside iOS Simulator."""
import json
from pathlib import Path
import platform
import re
import shutil
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
    # iOS 26.x can stall during first boot on hosted Intel runners. Prefer the
    # newest installed iOS 18 runtime for the official x86_64 Godot template.
    stable_intel = [r for r in runtimes if r['version'].split('.')[0] == '18']
    candidates = stable_intel if platform.machine() == 'x86_64' and stable_intel else runtimes
    runtime = max(candidates, key=lambda r: tuple(int(v) for v in r['version'].split('.')))
    types = json.loads(command('list', 'devicetypes', '-j'))['devicetypes']
    phones = [t for t in types if t.get('productFamily') == 'iPhone']
    preferred = next((t for t in phones if t['name'] == 'iPhone 16 Pro'), None)
    phone = preferred or next((t for t in reversed(phones) if 'Pro' in t['name']), phones[-1])
    udid = command('create', 'BlendEngine native IPA QA', phone['identifier'], runtime['identifier']).strip()
    return udid, runtime['name'], phone['name']


def _launch_pid(console, bundle):
    match = re.search(r'(?:^|\n)' + re.escape(bundle) + r':\s*(\d+)\s*(?:\n|$)', console)
    return int(match.group(1)) if match else None


def _boot_ready(udid, log):
    try:
        result = subprocess.run(['xcrun', 'simctl', 'bootstatus', udid, '-b'],
            capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as error:
        def decoded(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else (value or '')
        Path(log).write_text(decoded(error.stdout) + decoded(error.stderr), encoding='utf-8')
        raise RuntimeError('Simulator boot timed out after 600 seconds; inspect ' + Path(log).name) from error
    Path(log).write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Simulator bootstatus failed (%d); inspect %s' % (result.returncode, Path(log).name))


def _scenario_text(console, unified, bundle, pid):
    """Read only this launch's engine events, never an earlier process's PASS."""
    messages = [console]
    for line in unified.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue  # log stream also prints a filtering/startup banner.
        if not isinstance(event, dict) or event.get('subsystem') != bundle:
            continue
        try:
            same_process = int(event.get('processID', -1)) == pid
        except (TypeError, ValueError):
            same_process = False
        if same_process:
            messages.append(str(event.get('category', '')) + ': ' + str(event.get('eventMessage', '')))
    return '\n'.join(messages)


def _verify_video(path, returncode):
    path = Path(path)
    if returncode != 0 or not path.is_file() or path.stat().st_size <= 32:
        raise RuntimeError('Simulator video recording failed or produced an empty file')
    with path.open('rb') as movie:
        if movie.read(8)[4:8] != b'ftyp':
            raise RuntimeError('Simulator recording does not have an MP4 ftyp header')
    result = {'recorder_exit_code': returncode, 'bytes': path.stat().st_size,
              'mp4_ftyp_verified': True, 'multiple_frames_verified': False}
    ffprobe = shutil.which('ffprobe')
    if ffprobe:
        probe = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-count_frames',
            '-show_entries', 'stream=nb_read_frames,width,height', '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=60, check=True)
        streams = json.loads(probe.stdout).get('streams', [])
        if (not streams or int(streams[0].get('nb_read_frames', 0)) < 2
                or streams[0].get('width', 0) <= 0 or streams[0].get('height', 0) <= 0):
            raise RuntimeError('Simulator recording must contain multiple native video frames')
        result.update(multiple_frames_verified=True, frames=int(streams[0]['nb_read_frames']),
                      width=streams[0]['width'], height=streams[0]['height'])
    return result


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
        # Godot's iOS logger writes os_log info events, not stdout. Start a
        # separate fresh stream before launching so early engine errors are
        # included; filtering by the new PID below rejects stale PASS events.
        unified = proof / (label + '-unified.ndjson')
        unified_stream = unified.open('w')
        handles.append(unified_stream)
        logger = subprocess.Popen(['xcrun', 'simctl', 'spawn', udid, 'log', 'stream',
            '--level', 'info', '--style', 'ndjson', '--timeout', '300',
            '--predicate', 'subsystem == "' + bundle + '"'],
            stdout=unified_stream, stderr=subprocess.STDOUT)
        processes.append(logger)
        time.sleep(1)
        if logger.poll() is not None:
            raise RuntimeError('Could not start simulator unified logging: ' + unified.read_text(errors='replace'))
        log = proof / (label + '.log')
        stream = log.open('w')
        handles.append(stream)
        proc = subprocess.Popen(['xcrun', 'simctl', 'launch', '--terminate-running-process',
            '--console', udid, bundle, *args], stdout=stream, stderr=subprocess.STDOUT)
        processes.append(proc)
        time.sleep(1)
        pid = _launch_pid(log.read_text(errors='replace'), bundle)
        if pid is None:
            # The --console launch banner can remain buffered. A second launch
            # without --terminate is idempotent and returns the running PID.
            receipt = command('launch', udid, bundle, *args, timeout=30)
            (proof / (label + '-pid.txt')).write_text(receipt, encoding='utf-8')
            pid = _launch_pid(receipt, bundle)
        if pid is None:
            raise RuntimeError('Could not identify native simulator launch PID: ' + log.read_text(errors='replace')[-2000:])
        return proc, {'console': log, 'unified': unified, 'logger': logger, 'pid': pid}

    def capture_text(capture):
        return _scenario_text(capture['console'].read_text(errors='replace'),
            capture['unified'].read_text(errors='replace'), bundle, capture['pid'])

    def check_log(capture):
        content = capture_text(capture)
        if ('SCRIPT ERROR' in content or 'LAST_SIGNAL_SMOKE_FAIL' in content
                or 'LAST_SIGNAL_AGENT_FAIL' in content):
            raise RuntimeError('Native simulator scenario failed; inspect ' + capture['unified'].name)
        if capture['logger'].poll() is not None:
            raise RuntimeError('Simulator unified logging stopped before scenario completion')
        return content

    def stop_logger(capture):
        logger = capture['logger']
        if logger.poll() is None:
            logger.terminate()
            try:
                logger.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.kill()
                logger.wait(timeout=10)

    def state():
        try:
            return json.loads((data / 'Documents/qa_state.json').read_text())
        except (OSError, ValueError):
            return None

    def await_state(predicate, timeout=120, capture=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if capture:
                check_log(capture)
            value = state()
            if value and predicate(value):
                return value
            time.sleep(1)
        raise RuntimeError('iOS native state timeout: ' + str(state()))

    def await_marker(proc, capture, marker, timeout=240):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            content = check_log(capture)
            if marker in content:
                # UIKit can keep the process alive after SceneTree.quit().
                # The explicit PASS marker is the completed scenario boundary;
                # a still-running application is terminated only as teardown.
                if proc.poll() is not None and proc.returncode:
                    raise RuntimeError('Simulator exited nonzero after ' + marker)
                if proc.poll() is None:
                    command('terminate', udid, bundle, check=False)
                    proc.wait(timeout=30)
                stop_logger(capture)
                return content
            if proc.poll() is not None:
                raise RuntimeError('Simulator game exited before ' + marker + ': ' + content[-2000:])
            time.sleep(1)
        raise RuntimeError('Simulator scenario timed out: ' + marker)

    try:
        command('boot', udid)
        subprocess.run(['open', '-a', 'Simulator', '--args', '-CurrentDeviceUDID', udid], check=True)
        _boot_ready(udid, proof/'simulator-boot.log')
        command('install', udid, app, timeout=120)
        data = Path(command('get_app_container', udid, bundle, 'data').strip())
        report['data_container_verified'] = data.is_dir()
        recording = subprocess.Popen(['xcrun', 'simctl', 'io', udid, 'recordVideo',
            '--codec=h264', str(proof/'iOS-native-gameplay.mp4')], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        proc, capture = launch('normal-launch')
        normal = await_state(lambda s: s.get('native') and s.get('floor')
            and s.get('event') == 'playing' and len(s.get('npc_agents', [])) == 1
            and s['npc_agents'][0].get('walked', 0) > .2
            and s['npc_agents'][0].get('walk_pose_changes', 0) > 0, capture=capture)
        report['normal_launcher'] = True
        report['native_normal_state'] = normal
        if proc.poll() is not None:
            raise RuntimeError('Normal native game exited before screenshot capture')
        if normal.get('clues') != 0 or normal.get('walked', 0) > .1:
            raise RuntimeError('Guide must not collect clues or move the idle player')
        command('io', udid, 'screenshot', proof/'iOS-native-scene.png')
        time.sleep(3)
        check_log(capture)
        if proc.poll() is not None:
            raise RuntimeError('Normal native game exited during capture')
        recording.send_signal(signal.SIGINT)
        recording.wait(timeout=30)
        report['video'] = _verify_video(proof/'iOS-native-gameplay.mp4', recording.returncode)
        recording = None
        command('terminate', udid, bundle)
        proc.wait(timeout=30)
        stop_logger(capture)

        proc, capture = launch('full-story', ['--audio-driver', 'Dummy', '--', '--smoke-test'])
        await_marker(proc, capture, 'LAST_SIGNAL_SMOKE_PASS')
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
        proc, capture = launch('npc-physics', ['--audio-driver', 'Dummy', '--script', 'res://tests/agent_smoke.gd'])
        text = await_marker(proc, capture, 'LAST_SIGNAL_AGENT_PASS')
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
