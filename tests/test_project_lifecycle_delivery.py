import importlib.util
import json
from pathlib import Path
import git
import pytest
from click.testing import CliRunner
from archguard import usage, project_control as control, dispatch_queue
from archguard.cli.main import cli
from archguard.storage import atomic_json, metadata_path, read_json
from tests.control_helpers import authorize


def hook_module():
    spec = importlib.util.spec_from_file_location('startup_hook', Path(__file__).parents[1] / 'plugins/ide-audit/scripts/session_start.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hook_default_decline_pause_and_b_role(tmp_path):
    git.Repo.init(tmp_path)
    hook = hook_module()
    def message(**kw):
        return hook.check(dict(cwd=str(tmp_path), **kw))['hookSpecificOutput']['additionalContext']
    assert '尚未授权' in message()
    assert not (tmp_path / '.ide_audit').exists()
    hook.decline(tmp_path, confirmed=True)
    assert control.status(tmp_path)['status'] == 'declined'
    assert '不重复询问' in message()
    authorize(tmp_path)
    assert 'A 开始编码前' in message()
    atomic_json(metadata_path(tmp_path, 'session.json'), {'thread_id': 'b'})
    assert '你是审计 B' in message(session_id='b')
    control.pause(tmp_path)
    assert '不重复询问' in message(session_id='a')


def test_cli_install_without_consent_and_disabled_hook_do_nothing(tmp_path):
    runner = CliRunner()
    assert runner.invoke(cli, ['--project-root', str(tmp_path), 'install']).exit_code != 0
    assert runner.invoke(cli, ['--project-root', str(tmp_path), 'audit', '--notify']).exit_code == 0
    assert not (tmp_path / '.ide_audit').exists()


def test_paused_jobs_need_explicit_retry_after_a(tmp_path):
    authorize(tmp_path)
    dispatch_queue.enqueue(tmp_path, 'a' * 40, launch=False)
    control.pause(tmp_path)
    control.resume(tmp_path)
    state = control.status(tmp_path)
    atomic_json(metadata_path(tmp_path, 'project-control.json'), dict(state, status='enabled'))
    class Manager:
        def audit(self, report): pytest.fail('旧任务不能自动派发')
    dispatch_queue.drain(tmp_path, Manager())
    assert read_json(metadata_path(tmp_path, 'queue', 'a' * 40 + '.json'))['status'] == 'held_after_pause'


def test_malformed_authorization_is_disabled(tmp_path):
    authorize(tmp_path)
    state = control.status(tmp_path)
    atomic_json(metadata_path(tmp_path, 'project-control.json'), dict(state, revision='1'))
    assert control.status(tmp_path)['status'] == 'unselected'


def test_usage_rollout_turns_duplicates_partial_tail_and_reset(tmp_path, monkeypatch):
    home = tmp_path / 'host'; home.mkdir()
    monkeypatch.setenv('CODEX_HOME', str(home))
    log = home / 'b.jsonl'
    entries = [{'type': 'session_meta', 'payload': {'id': 'b', 'cwd': str(tmp_path)}}]
    def turn(identifier): entries.append({'type': 'turn_context', 'payload': {'turn_id': identifier}})
    def count(n):
        data = dict(input_tokens=n-2, output_tokens=2, cached_input_tokens=0, reasoning_output_tokens=0, total_tokens=n)
        entries.append({'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'total_token_usage': data, 'last_token_usage': data}}})
    turn('t1'); count(20); count(20); turn('t2'); count(30)
    def write(): log.write_text(''.join(json.dumps(e)+'\n' for e in entries)+'{"partial":', encoding='utf-8')
    class Client:
        def request(self, method, params):
            if method == 'account/usage/read': return {'threadUsage': None}
            return {'thread': {'id': 'b', 'cwd': str(tmp_path), 'path': str(log)}}
    write()
    result = usage.capture(tmp_path, Client(), 'b')
    assert result['counts']['totalTokens'] == 30
    assert result['per_turn']['t1']['totalTokens'] == 20
    assert result['per_turn']['t2']['totalTokens'] == 10
    count(5); write()
    assert usage.capture(tmp_path, Client(), 'b')['per_turn']['t2']['totalTokens'] is None
    entries[0]['payload']['id'] = 'another-b'; write()
    assert usage.capture(tmp_path, Client(), 'b')['status'] == 'unknown'


def test_counters_from_different_sources_cannot_be_subtracted(tmp_path):
    result = usage.save(tmp_path, 'b', 't', None, {'source': 'a', 'counts': {'totalTokens': 10}},
                        {'source': 'b', 'counts': {'totalTokens': 20}})
    assert result['counts']['totalTokens'] is None


def test_packaged_hook_command_uses_host_plugin_root(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    plugin = tmp_path / 'plugin with spaces'
    plugin.mkdir(); (plugin / 'scripts').mkdir()
    source = Path(__file__).parents[1] / 'plugins/ide-audit'
    shutil.copy2(source / 'scripts/session_start.py', plugin / 'scripts/session_start.py')
    project = tmp_path / 'project'; project.mkdir(); git.Repo.init(project)
    handler = json.loads((source / 'hooks/hooks.json').read_text(encoding='utf-8'))['hooks']['SessionStart'][0]['hooks'][0]
    command = handler['commandWindows' if os.name == 'nt' else 'command']
    # 测试环境选择当前 Python；其余内容完全使用发布 Hook 命令。
    command = '"'+sys.executable+'"'+command[command.index(' '):]
    result = subprocess.run(command, shell=True, input=json.dumps({'cwd': str(project), 'session_id': 'a'}),
                            text=True, capture_output=True, env=dict(os.environ, PLUGIN_ROOT=str(plugin)), timeout=10)
    assert result.returncode == 0, result.stderr
    assert '尚未授权' in json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
    assert not (project / '.ide_audit').exists()


def test_old_desktop_ready_is_not_exposed_after_resume(tmp_path):
    from archguard.adapters.codex.desktop_bridge import claim
    from archguard.adapters.codex.session_manager import AppServerError
    authorize(tmp_path)
    identifier = 'e' * 40
    dispatch_queue.enqueue(tmp_path, identifier, launch=False)
    queue_path = metadata_path(tmp_path, 'queue', identifier + '.json')
    atomic_json(queue_path, dict(read_json(queue_path), status='awaiting_desktop'))
    atomic_json(metadata_path(tmp_path, 'jobs', identifier, 'dispatch.json'), {'status': 'desktop_ready', 'thread_id': 'b'})
    control.pause(tmp_path); control.resume(tmp_path)
    atomic_json(metadata_path(tmp_path, 'project-control.json'), dict(control.status(tmp_path), status='enabled'))
    assert dispatch_queue.status(tmp_path, identifier)['desktop_pending'] == []
    with pytest.raises(AppServerError, match='retry-audit'):
        claim(tmp_path, identifier)
