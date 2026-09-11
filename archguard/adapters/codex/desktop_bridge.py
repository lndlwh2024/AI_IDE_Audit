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
    template = (Path(__file__).parents[2] / 'templates/skill_codex_audit.md').read_text(encoding='utf-8')
    message = (template + '\n本轮是独立架构审计，不能代替 A 进行开发。以以下固定需求和提交证据裁决，'
               '不要用以往聊天扩张本轮授权。原生桌面允许读写，但本审计任务只需要读取证据和输出报告。\n'
               '最终仅输出一个 JSON 对象：{"request_id": "' + request_id + '", "verdict": <裁决对象>}。'
               '裁决对象必须符合以下 schema：\n' + json.dumps(VERDICT_SCHEMA, ensure_ascii=False) +
               '\n固定提交事实包：\n' + audit_packet(report))
    atomic_json(metadata_path(manager.root, 'jobs', report.audit_id, 'dispatch.json'), {
        'status': 'desktop_ready', 'thread_id': thread_id, 'request_id': request_id,
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
                    envelope = json.loads(text)
                except ValueError:
                    continue
                if not isinstance(envelope, dict) or envelope.get('request_id') != state['request_id']:
                    continue
                result = manager._save_verdict(get_result(root, identifier), json.dumps(envelope['verdict'], ensure_ascii=False),
                                               state['thread_id'], turn['id'])
                usage.save(root, state['thread_id'], turn['id'], identifier, state.get('usage_before'), usage_after)
                queue_path = metadata_path(root, 'queue', identifier + '.json')
                queue = read_json(queue_path)
                if queue:
                    atomic_json(queue_path, dict(queue, status='completed'))
                return result
        raise AppServerError('B 尚未给出本次请求的有效裁决；不得由 A 补写或重复发送')
