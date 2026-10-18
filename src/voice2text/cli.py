"""Project-scoped setup and service lifecycle."""

import argparse
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

from .config import LOCAL, MODEL_REPO, ROOT, configure_environment, load_config

PID_FILE = LOCAL / 'server.json'
LOG_FILE = LOCAL / 'server.log'
NATIVE_HOST_NAME = 'com.voice2text.host'


def process_matches(identity: dict, started: str, command: str) -> bool:
    root = identity.get('root', '')
    return (bool(root) and identity.get('started') == started and
            command == f'{root}/.venv/bin/python -m voice2text.cli serve')


def process_info(pid: int):
    try:
        command = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True, stderr=subprocess.DEVNULL).strip()
        started = subprocess.check_output(['ps', '-p', str(pid), '-o', 'lstart='], text=True, stderr=subprocess.DEVNULL).strip()
        return started, command
    except (subprocess.CalledProcessError, OSError):
        return '', ''


def owned_process():
    if not PID_FILE.exists():
        return None
    try:
        identity = json.loads(PID_FILE.read_text())
        started, command = process_info(identity['pid'])
        return identity if process_matches(identity, started, command) else None
    except (ValueError, KeyError, TypeError):
        return None


def port_available(port: int):
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1', port)) != 0


def service_health(port: int):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def safe_package_files(root: Path) -> list[Path]:
    exact = ['README.md', 'pyproject.toml', 'uv.lock', 'voice2text-run', 'voice2text-native-host', '.gitignore']
    directories = {'extension': {'.js', '.html', '.css', '.json', '.png', '.svg'},
                   'src/voice2text': {'.py'}}
    paths = [root / name for name in exact if (root / name).is_file()]
    paths.extend(path for path in (root / 'docs/usage.md',) if path.is_file())
    for dirname, suffixes in directories.items():
        base = root / dirname
        if base.exists():
            paths.extend(p for p in base.rglob('*') if p.is_file() and p.suffix in suffixes and
                         not p.name.startswith('.') and not p.is_symlink())
    return sorted(paths, key=lambda path: str(path.relative_to(root)))


def setup():
    configure_environment()
    config = load_config()
    if not (config.model_path / 'weights.npz').exists():
        from huggingface_hub import snapshot_download
        config.model_path.mkdir(parents=True, exist_ok=True)
        snapshot_download(MODEL_REPO, local_dir=config.model_path, allow_patterns=['config.json', 'weights.npz'])
    print('Voice2Text model and local connection key are ready.')


def serve():
    configure_environment()
    config = load_config()
    from .recognizer import Recognizer
    recognizer = Recognizer(config.model_path)
    recognizer.load()
    from .server import create_app
    import uvicorn
    uvicorn.run(create_app(config, recognizer), host='127.0.0.1', port=config.port, log_level='warning', access_log=False)


def start():
    config = load_config()
    if owned_process():
        print('Voice2Text is already running.')
        return
    if not port_available(config.port):
        raise SystemExit(f'Port {config.port} is already in use. Stop the owning service or choose another port.')
    LOG_FILE.touch(mode=0o600, exist_ok=True)
    with LOG_FILE.open('ab') as log:
        child = subprocess.Popen([str(ROOT / '.venv/bin/python'), '-m', 'voice2text.cli', 'serve'],
                                 cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 start_new_session=True, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')})
    identity = None
    for _ in range(50):
        started, command = process_info(child.pid)
        if started and command:
            identity = {'pid': child.pid, 'started': started, 'root': str(ROOT)}
            break
        if child.poll() is not None:
            break
        time.sleep(.1)
    if not identity:
        raise SystemExit('Voice2Text could not start. Check .local/server.log.')
    fd = os.open(PID_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(identity, handle)
    for _ in range(150):
        if child.poll() is not None:
            raise SystemExit('Voice2Text failed to load its model. Check .local/server.log.')
        health = service_health(config.port)
        if health and health.get('ready'):
            print('Voice2Text is ready on 127.0.0.1:8766.')
            return
        time.sleep(.2)
    raise SystemExit('Voice2Text is still loading. Run ./voice2text-run status to check progress.')


def status():
    result = service_status()
    print(result['message'])


def service_status():
    config = load_config()
    identity = owned_process()
    health = service_health(config.port)
    listener = listener_pid(config.port) if health or not identity else None
    pid = identity['pid'] if identity else listener
    address = f'127.0.0.1:{config.port}'
    if identity and health and health.get('ready'):
        state = 'ready'
        message = f'Voice2Text ready · {address} · PID {pid} · model {health["model"]}.'
    elif identity:
        state = 'starting'
        message = f'Voice2Text process exists · {address} · PID {pid}; model is loading or unavailable.'
    elif health:
        state = 'unverified'
        message = f'{address} responds · listener PID {pid or "unknown"} · process ownership unverified.'
    else:
        state = 'stopped'
        message = f'Voice2Text is stopped · configured address {address} · PID none.'
    return {'state': state, 'port': config.port, 'pid': pid, 'message': message}


def listener_pid(port: int) -> int | None:
    try:
        result = subprocess.check_output(
            ['lsof', '-nP', f'-iTCP:{port}', '-sTCP:LISTEN', '-t'],
            text=True, stderr=subprocess.DEVNULL,
        ).strip().splitlines()
        return int(result[0]) if result else None
    except (subprocess.CalledProcessError, OSError, ValueError):
        return None


def stop():
    identity = owned_process()
    if not identity:
        print('No owned Voice2Text process is running. Nothing was stopped.')
        return
    os.kill(identity['pid'], signal.SIGTERM)
    for _ in range(40):
        if not owned_process():
            PID_FILE.unlink(missing_ok=True)
            print('Voice2Text stopped.')
            return
        time.sleep(.1)
    raise SystemExit('Voice2Text did not exit; check its process before retrying.')


def restart():
    stop()
    start()


def logs(lines: int = 80):
    if not LOG_FILE.is_file():
        print('No Voice2Text log file exists yet.')
        return
    try:
        output = subprocess.check_output(['tail', '-n', str(lines), str(LOG_FILE)], text=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise SystemExit(f'Could not read Voice2Text logs: {exc}') from exc
    print(output, end='' if output.endswith('\n') else '\n')


def open_browser():
    for app in ('Google Chrome', 'Brave Browser'):
        result = subprocess.run(['open', '-a', app], capture_output=True, text=True)
        if result.returncode == 0:
            print(f'Opened {app}.')
            return
    raise SystemExit('Could not find Google Chrome or Brave Browser.')


def install_native_host():
    print('Load the Voice2Text extension in each browser first, then copy its ID from the extension details page.')
    extension_ids = {}
    for browser in ('Chrome', 'Brave'):
        extension_id = input(f'{browser} extension ID (press Enter to skip): ').strip()
        if extension_id and not re.fullmatch(r'[a-p]{32}', extension_id):
            raise SystemExit(f'{browser} extension ID must contain 32 letters from a to p.')
        if extension_id:
            extension_ids[browser] = extension_id
    if not extension_ids:
        raise SystemExit('No browser extension ID was provided.')

    host_path = ROOT / 'voice2text-native-host'
    host_path.chmod(0o700)
    manifest = {'name': NATIVE_HOST_NAME, 'description': 'Voice2Text local speech service launcher',
                'path': str(host_path), 'type': 'stdio',
                'allowed_origins': [f'chrome-extension://{extension_id}/'
                                    for extension_id in sorted(set(extension_ids.values()))]}
    locations = {
        Path.home() / 'Library/Application Support/Google/Chrome/NativeMessagingHosts',
        Path.home() / 'Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts',
    }
    for directory in sorted(locations):
        directory.mkdir(parents=True, exist_ok=True)
        manifest_path = directory / f'{NATIVE_HOST_NAME}.json'
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        manifest_path.chmod(0o600)
        print(f'Browser launcher registered: {manifest_path}')
    allowlist = LOCAL / 'native-host.json'
    allowlist.write_text(json.dumps({'extension_ids': sorted(extension_ids.values())}, indent=2) + '\n')
    allowlist.chmod(0o600)
    print('Restart the browser once to activate the native launcher.')


def native_host(origin: str):
    try:
        registered = json.loads((LOCAL / 'native-host.json').read_text())
        extension_id = origin.removeprefix('chrome-extension://').rstrip('/')
        if not re.fullmatch(r'[a-p]{32}', extension_id) or extension_id not in registered.get('extension_ids', []):
            raise ValueError('Caller is not registered for Voice2Text.')
        raw_length = sys.stdin.buffer.read(4)
        if len(raw_length) != 4:
            raise ValueError('Missing native message.')
        length = int.from_bytes(raw_length, 'little')
        if length <= 0 or length > 1024 * 1024:
            raise ValueError('Native message size is invalid.')
        request = json.loads(sys.stdin.buffer.read(length))
        if not isinstance(request, dict) or request.get('command') != 'start':
            raise ValueError('Unsupported native command.')
        result = subprocess.run([sys.executable, '-m', 'voice2text.cli', 'start'], cwd=ROOT,
                                capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError((result.stdout or result.stderr or 'Service startup failed.').strip())
        state = service_status()
        response = {'ok': state['state'] == 'ready', 'state': state['state'], 'port': state['port'],
                    'pid': state['pid'], 'error': None if state['state'] == 'ready' else state['message']}
    except Exception as exc:
        response = {'ok': False, 'error': str(exc)[:1000]}
    payload = json.dumps(response, separators=(',', ':')).encode('utf-8')
    sys.stdout.buffer.write(len(payload).to_bytes(4, 'little') + payload)
    sys.stdout.buffer.flush()


def native_host_entry(origin: str | None):
    if not origin:
        raise SystemExit('Native host must be launched by a registered browser extension.')
    native_host(origin)


def check():
    config = load_config()
    python = ROOT / '.venv/bin/python'
    model_present = (config.model_path / 'weights.npz').is_file()
    print(f'Project: {ROOT}')
    print(f'Python environment: {"ready" if python.is_file() else "missing"} ({python})')
    print(f'Speech model: {"present" if model_present else "missing"} ({config.model_path})')
    health = service_health(config.port)
    identity = owned_process()
    if health and health.get('ready'):
        print(f'Service: ready · 127.0.0.1:{config.port} · PID {identity["pid"] if identity else listener_pid(config.port) or "unknown"}')
    elif health:
        print(f'Service: responding but not ready · 127.0.0.1:{config.port} · PID {identity["pid"] if identity else listener_pid(config.port) or "unknown"}')
    elif port_available(config.port):
        print(f'Service: stopped · 127.0.0.1:{config.port} is available')
    else:
        print(f'Service: port conflict · 127.0.0.1:{config.port} is occupied by an unverified process')


def menu():
    actions = {
        '1': ('Start service', start),
        '2': ('Stop service', stop),
        '3': ('Show status', status),
        '4': ('Restart service', restart),
        '5': ('Show logs', logs),
        '6': ('Check configuration', check),
        '7': ('Open browser', open_browser),
        '8': ('Install browser launcher', install_native_host),
    }
    while True:
        print('\nVoice2Text LaunchPad')
        for key, (label, _) in actions.items():
            print(f'{key}. {label}')
        print('e. Exit menu (keep services running)')
        print('q. Stop service and exit')
        try:
            choice = input('Select: ').strip().lower()
        except EOFError:
            print('\nExit menu; service state is unchanged.')
            return
        if choice == 'e':
            print('Exit menu; service state is unchanged.')
            return
        if choice == 'q':
            try:
                stop()
            except SystemExit as exc:
                print(exc)
                continue
            return
        action = actions.get(choice)
        if not action:
            print('Invalid selection. Choose 1–8, e, or q.')
            continue
        print()
        try:
            action[1]()
        except SystemExit as exc:
            print(exc)


def package():
    destination = ROOT / 'dist' / 'Voice2Text.zip'
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in safe_package_files(ROOT):
            archive.write(path, path.relative_to(ROOT))
    print(destination)


def main():
    parser = argparse.ArgumentParser(prog='voice2text-run')
    parser.add_argument('command', nargs='?', choices=['setup', 'start', 'stop', 'restart', 'status', 'logs', 'check', 'open', 'install-host', 'copy-key', 'package', 'serve', 'native-host'])
    parser.add_argument('host_origin', nargs='?')
    arguments = parser.parse_args()
    command = arguments.command
    if command is None: menu()
    elif command == 'setup': setup()
    elif command == 'start': start()
    elif command == 'stop': stop()
    elif command == 'restart': restart()
    elif command == 'status': status()
    elif command == 'logs': logs()
    elif command == 'check': check()
    elif command == 'open': open_browser()
    elif command == 'install-host': install_native_host()
    elif command == 'copy-key':
        subprocess.run(['pbcopy'], input=load_config().token, text=True, check=True)
        print('Connection key copied to clipboard.')
    elif command == 'package': package()
    elif command == 'serve': serve()
    elif command == 'native-host': native_host_entry(arguments.host_origin)


if __name__ == '__main__': main()
