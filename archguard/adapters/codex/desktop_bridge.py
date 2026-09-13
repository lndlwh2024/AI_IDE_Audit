"""桌面已持有 B 时的原生派发交接；结果必须读取真实 B 的新轮次。"""
from archguard.delivery import audit_packet
import json
from archguard import project_control as control
from archguard import usage
from pathlib import Path
from uuid import uuid4
from archguard.storage import metadata_path, atomic_json, read_json, transaction
from archguard.runtime import get_result, _key
from .session_manager import AppServerError, CodexSessionManager, VERDICT_SCHEMA


def verify_thread(manager, client, thread_id, include_turns=True):
    thread = client.request('thread/read', {'threadId': thread_id, 'includeTurns': include_turns})['thread']
    if Path(thread['cwd']).resolve() != manager.root or thread.get('projectId') != manager._project_id(client):
        raise AppServerError('桌面 B 的目录或项目归属不匹配')
    return thread


def prepare_dispatch(manager, client, report, thread_id):
    thread = verify_thread(manager, client, thread_id)
    client.request('thread/name/set', {'threadId':thread_id, 'name':'🔔' + manager.root.name + '项目审计窗口-' + str(read_json(manager.session_file, {}).get('sequence',1))})
    request_id = uuid4().hex
    from archguard.delivery import build_message
    message = build_message(report, request_id)
    from archguard.runtime import save_b_input
    input_path = save_b_input(manager.root, report, message)
    atomic_json(metadata_path(manager.root, 'jobs', report.audit_id, 'dispatch.json'), {
        'status': 'desktop_ready', 'thread_id': thread_id, 'request_id': request_id, 'input_path':input_path,
        'previous_turn_ids': [t['id'] for t in thread.get('turns', [])], 'message': message})
    return {'desktop_dispatch_required': True, 'thread_id': thread_id}


def claim(root, audit_id, manager=None):
    control.require(root)
    identifier = _key(audit_id)
    manager = manager or CodexSessionManager(root)
    path = metadata_path(root, 'jobs', identifier, 'dispatch.json')
    with transaction(root, 'codex-session'):
        state = read_json(path, {})
        queued = read_json(metadata_path(root, 'queue', identifier + '.json'), {})
        if queued and queued.get('epoch') != control.status(root).get('epoch'):
            raise AppServerError('暂停前请求须明确 retry-audit，不能自动领取旧队列')
        if state.get('status') != 'desktop_ready':
            raise AppServerError('没有可领取的桌面派发；已领取时必须先核对原 B，不能重复发送')
        with manager.client_factory() as client:
            thread = verify_thread(manager, client, state['thread_id'])
            state['usage_before'] = usage.capture(root, client, state['thread_id'])
        if thread.get('status', {}).get('type') == 'active':
            return {'ready': False, 'reason': 'B 正在处理上一轮，请等待', 'thread_id': state['thread_id']}
        state['previous_turn_ids'] = [t['id'] for t in thread.get('turns', [])]
        control.require(root)
        state['status'] = 'desktop_sending'
        atomic_json(path, state)
        return {'ready': True, 'thread_id': state['thread_id'], 'prompt': state['message'], 'audit_id': identifier, 'project_revision': control.status(root)['revision']}


def collect(root, audit_id, manager=None):
    identifier = _key(audit_id)
    manager = manager or CodexSessionManager(root)
    path = metadata_path(root, 'jobs', identifier, 'dispatch.json')
    with transaction(root, 'codex-session'):
        state = read_json(path, {})
        if state.get('status') == 'completed':
            return read_json(metadata_path(root, 'verdicts', identifier + '.json'))
        if state.get('status') != 'desktop_sending':
            raise AppServerError('该任务尚未领取桌面派发')
        with manager.client_factory() as client:
            thread = verify_thread(manager, client, state['thread_id'])
            usage_after = usage.capture(root, client, state['thread_id'])
        for turn in thread.get('turns', []):
            if turn['id'] in state['previous_turn_ids'] or turn.get('status') != 'completed':
                continue
            for item in reversed(turn.get('items', [])):
                if item.get('type') != 'agentMessage':
                    continue
                text = item.get('text', '').strip()
                if text.startswith('```json') and text.endswith('```'):
                    text = text[7:-3].strip()
                try:
                    from archguard.presentation import parse_result
                    envelope = parse_result(text)
                except ValueError:
                    continue
                if not isinstance(envelope, dict) or envelope.get('request_id') != state['request_id']:
                    continue
                result = manager._save_verdict(get_result(root, identifier), json.dumps(envelope['verdict'], ensure_ascii=False),
                                               state['thread_id'], turn['id'], presentation_text=text)
                usage.save(root, state['thread_id'], turn['id'], identifier, state.get('usage_before'), usage_after)
                queue_path = metadata_path(root, 'queue', identifier + '.json')
                queue = read_json(queue_path)
                if queue:
                    atomic_json(queue_path, dict(queue, status='completed'))
                return result
        raise AppServerError('B 尚未给出本次请求的有效裁决；不得由 A 补写或重复发送')
