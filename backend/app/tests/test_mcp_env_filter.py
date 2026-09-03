from __future__ import annotations

import os
import shutil

from backend.app.platform_api import mcp_hub


def test_blocked_keys_are_filtered_case_insensitively_and_not_persisted():
    env = {
        'LD_PRELOAD': '/tmp/evil.so',
        'PATH': '/tmp/bin',
        'NODE_OPTIONS': '--require /tmp/evil.js',
        'dyld_library_path': '/tmp/lib',
        'FOO': 'bar',
    }
    filtered = mcp_hub._filter_mcp_env(env)
    assert filtered == {'FOO': 'bar'}
    secured = mcp_hub._encrypt_env(env)
    assert set(secured) == {'FOO'}


def test_legal_env_is_forwarded_and_service_path_resolves(monkeypatch):
    service_path = os.environ.get('PATH', '')
    monkeypatch.setenv('PATH', service_path)
    child = mcp_hub._minimal_subprocess_env({'FOO': 'bar', 'Path': '/tmp/override'})
    assert child['FOO'] == 'bar'
    assert child['PATH'] == service_path
    assert shutil.which('sh', path=service_path) == shutil.which('sh')


def test_mixed_keys_drop_only_blocked_entries():
    child = mcp_hub._minimal_subprocess_env({
        'A': '1', 'LD_LIBRARY_PATH': '/tmp/lib', 'B': '2', 'Shell': '/bin/sh',
    })
    assert child['A'] == '1'
    assert child['B'] == '2'
    assert 'LD_LIBRARY_PATH' not in child
    assert 'Shell' not in child
