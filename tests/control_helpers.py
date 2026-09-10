"""旧功能测试显式准备授权前提；未授权行为在独立测试中验证。"""
from archguard import project_control as control
from archguard.storage import atomic_json, metadata_path


def authorize(root, project_id='test-project', ready=True):
    state = control.choose(root, project_id, True, confirmed=True)
    if ready:
        state['status'] = 'enabled'
        atomic_json(metadata_path(root, 'project-control.json'), state)
    return state
