"""独立 CLI 恢复不依赖已关闭 MCP，且保留授权和原请求校验。"""
import json
from click.testing import CliRunner
from archguard.cli.main import cli


def test_status_is_readonly_and_prepare_requires_consent(tmp_path):
    runner=CliRunner()
    result=runner.invoke(cli,['--project-root',str(tmp_path),'runtime-status'])
    assert result.exit_code==0
    assert json.loads(result.output)['transport']=='fresh-cli'
    assert not (tmp_path/'.ide_audit').exists()
    result=runner.invoke(cli,['--project-root',str(tmp_path),'prepare','--usage-thread-id','A'])
    assert result.exit_code!=0
    assert not (tmp_path/'.ide_audit/prepared.json').exists()


def test_cli_phase_continuity_and_compact_prepare(tmp_path, monkeypatch):
    import git
    from archguard import phase_usage
    from tests.control_helpers import authorize
    from archguard.storage import read_json,metadata_path
    repo=git.Repo.init(tmp_path)
    actor=git.Actor('test','test@example.com')
    (tmp_path/'note.md').write_text('base')
    repo.index.add(['note.md']);repo.index.commit('base',author=actor,committer=actor)
    authorize(tmp_path,'project')
    monkeypatch.setattr(phase_usage,'snapshot',lambda *a:{'status':'observed','source':'test','counts':{'totalTokens':100}})
    runner=CliRunner();prefix=['--project-root',str(tmp_path)]
    first=runner.invoke(cli,prefix+['phase-begin','--thread-id','A','--phase','prepare_commit'])
    assert first.exit_code==0,first.output
    identifier=json.loads(first.output)['measurement_id']
    prepared=runner.invoke(cli,prefix+['prepare','--usage-thread-id','A'])
    assert prepared.exit_code==0,prepared.output
    assert json.loads(prepared.output)['usage_measurement_count']==1
    assert 'declared_graph' not in prepared.output
    assert read_json(metadata_path(tmp_path,'prepared.json'))['usage_measurement_ids']==[identifier]
    done=runner.invoke(cli,prefix+['phase-finish',identifier])
    assert done.exit_code==0
    assert json.loads(done.output)['thread_total_tokens']==100


def test_desktop_claim_does_not_skip_authorization(tmp_path):
    result=CliRunner().invoke(cli,['--project-root',str(tmp_path),'desktop-claim','a'*40])
    assert result.exit_code!=0
