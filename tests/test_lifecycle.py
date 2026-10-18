import json
from pathlib import Path

import pytest

from voice2text import cli
from voice2text.cli import process_matches, safe_package_files


def test_pid_identity_requires_exact_start_and_project_path(tmp_path):
    identity = {'pid': 123, 'started': 'Sun Oct 18 12:00:00 2026', 'root': str(tmp_path)}
    assert process_matches(identity, 'Sun Oct 18 12:00:00 2026', f'{tmp_path}/.venv/bin/python -m voice2text.cli serve')
    assert not process_matches(identity, 'Sun Oct 18 12:00:01 2026', f'{tmp_path}/.venv/bin/python -m voice2text.cli serve')
    assert not process_matches(identity, identity['started'], '/other/python -m voice2text.cli serve')
    assert not process_matches(identity, identity['started'], f'/bin/sh -c "{tmp_path}/.venv/bin/python -m voice2text.cli serve"')


def test_package_allowlist_excludes_local_data(tmp_path):
    (tmp_path / 'extension').mkdir()
    (tmp_path / 'extension' / 'manifest.json').write_text('{}')
    (tmp_path / 'extension' / 'secret.txt').write_text('secret')
    (tmp_path / '.local').mkdir()
    (tmp_path / '.local' / 'config.json').write_text('token')
    (tmp_path / 'README.md').write_text('readme')
    files = safe_package_files(tmp_path)
    assert [str(file.relative_to(tmp_path)) for file in files] == ['README.md', 'extension/manifest.json']


def test_native_host_registration_allows_only_entered_browser_ids(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    local = project / '.local'
    local.mkdir(parents=True)
    (project / 'voice2text-native-host').write_text('#!/bin/sh\n')
    home = tmp_path / 'home'
    monkeypatch.setattr(cli, 'ROOT', project)
    monkeypatch.setattr(cli, 'LOCAL', local)
    monkeypatch.setattr(Path, 'home', lambda: home)
    extension_ids = iter(['a' * 32, 'b' * 32])
    monkeypatch.setattr('builtins.input', lambda _prompt: next(extension_ids))

    cli.install_native_host()

    expected_origins = [f'chrome-extension://{"a" * 32}/', f'chrome-extension://{"b" * 32}/']
    chrome_path = home / 'Library/Application Support/Google/Chrome/NativeMessagingHosts/com.voice2text.host.json'
    brave_path = home / 'Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts/com.voice2text.host.json'
    assert json.loads(chrome_path.read_text())['allowed_origins'] == expected_origins
    assert json.loads(brave_path.read_text())['allowed_origins'] == expected_origins
    assert json.loads((local / 'native-host.json').read_text())['extension_ids'] == ['a' * 32, 'b' * 32]
