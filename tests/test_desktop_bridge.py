"""原生 B 复用及裁决来源验证，不接受 A 提供的裁决替身。"""
import json
from types import SimpleNamespace
import pytest
from archguard.adapters.codex import desktop_bridge
from archguard.adapters.codex.session_manager import CodexSessionManager, AppServerError
from archguard.storage import atomic_json, read_json, metadata_path
from tests.test_delivery_regressions import make_report, verdict


class Client:
    def __init__(self, root):
        self.thread = {'id': 'native-b', 'cwd': str(root), 'projectId': 'project', 'status': {'type':'idle'},
                       'turns': [{'id':'old', 'status':'completed', 'items':[]}]}
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def request(self, method, params):
        if method == 'thread/name/set':
            self.thread['name'] = params['name']; return {}
        if method == 'thread/read': return {'thread':self.thread}
        if method == 'project/list': return {'data':[{'id':'project','roots':[{'path':self.thread['cwd']}]}]}
        if method == 'thread/resume':
            raise AppServerError('占用', {'code':-32600,'message':'thread native-b already has an active writer'})
        raise AssertionError(method)


def setup_manager(root):
    from tests.control_helpers import authorize
    authorize(root, "project")
    client=Client(root)
    manager=CodexSessionManager(root,client_factory=lambda:client)
    manager._config=lambda _: {}
    atomic_json(manager.session_file,{'project_root':str(root),'thread_id':'native-b','project_id':'project','sequence':2})
    report=make_report()
    atomic_json(metadata_path(root,'results','history',report.audit_id+'.json'),report.model_dump(mode='json'))
    return manager,client,report


def test_active_writer_routes_to_same_native_b(tmp_path):
    manager,client,report=setup_manager(tmp_path)
    result=manager.audit(report)
    assert result=={'desktop_dispatch_required':True,'thread_id':'native-b'}
    assert client.thread['name'] == '🔔' + tmp_path.name + '项目审计窗口-2'
    request=desktop_bridge.claim(tmp_path,report.audit_id,manager)
    assert request['ready'] and request['thread_id']=='native-b'
    with pytest.raises(AppServerError,match='不能重复'):
        desktop_bridge.claim(tmp_path,report.audit_id,manager)
    state=read_json(metadata_path(tmp_path,'jobs',report.audit_id,'dispatch.json'))
    nonce=state['request_id']
    client.thread['turns'].append({'id':'new','status':'completed','items':[{'type':'agentMessage',
        'text':'# 审计报告\n```json\n'+json.dumps({'request_id':nonce,'verdict':verdict()})+'\n```'}]})
    assert desktop_bridge.collect(tmp_path,report.audit_id,manager)==verdict()
    assert read_json(manager.session_file)['sequence']==2
    assert desktop_bridge.collect(tmp_path,report.audit_id,manager)==verdict()


def test_old_or_wrong_request_output_cannot_be_collected(tmp_path):
    manager,client,report=setup_manager(tmp_path)
    manager.audit(report)
    desktop_bridge.claim(tmp_path,report.audit_id,manager)
    client.thread['turns'].append({'id':'new','status':'completed','items':[{'type':'agentMessage',
        'text':json.dumps({'request_id':'other','verdict':verdict()})}]})
    with pytest.raises(AppServerError,match='不得由 A'):
        desktop_bridge.collect(tmp_path,report.audit_id,manager)
    assert not metadata_path(tmp_path,'verdicts',report.audit_id+'.json').exists()


def test_busy_native_b_does_not_consume_dispatch(tmp_path):
    manager,client,report=setup_manager(tmp_path)
    manager.audit(report)
    client.thread['status']={'type':'active'}
    assert not desktop_bridge.claim(tmp_path,report.audit_id,manager)['ready']
    state=read_json(metadata_path(tmp_path,'jobs',report.audit_id,'dispatch.json'))
    assert state['status']=='desktop_ready'
