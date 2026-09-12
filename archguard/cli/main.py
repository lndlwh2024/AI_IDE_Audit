"""统一命令入口，失败始终使用非零退出状态。"""
import json
import sys
from pathlib import Path
import click
from archguard import __version__


@click.group()
@click.version_option(__version__)
@click.option('--project-root', type=click.Path(exists=True, file_okay=False, path_type=Path), default='.')
@click.pass_context
def cli(ctx, project_root):
    """IDE_Audit：协同维护、提交事实与独立审计。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    ctx.obj = project_root.resolve()
    if ctx.invoked_subcommand in ('prompt', 'prepare', 'commit', 'retry-audit', 'drain'):
        from archguard.project_control import require
        execute(lambda: require(ctx.obj))


def execute(action):
    try:
        return action()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@cli.command()
@click.option('--ide', default='codex-desktop', type=click.Choice(['codex', 'codex-desktop']))
@click.option('--consent', is_flag=True, help='用户已明确授权当前项目；不能仅凭安装推断')
@click.pass_obj
def install(root, ide, consent):
    """安装统一守则、MCP 与提交 Hook。"""
    if not consent:
        raise click.ClickException('安装不等于项目授权。请在 A 明确同意开启后使用 install --consent。')
    from archguard.adapters.codex.installer import install_to_project
    from archguard.adapters.codex.session_manager import CodexSessionManager
    from archguard.project_control import choose
    def perform():
        manager = CodexSessionManager(root)
        with manager.client_factory() as client:
            project_id = manager._project_id(client)
        choose(root, project_id, True, confirmed=True)
        return install_to_project(root, ide)
    click.echo(json.dumps(execute(perform), ensure_ascii=False))


@cli.command()
@click.pass_obj
def uninstall(root):
    """卸载插件管理的入口，保留历史数据。"""
    from archguard.adapters.codex.installer import uninstall_from_project
    from archguard.project_control import pause
    execute(lambda: pause(root))
    click.echo(json.dumps(execute(lambda: uninstall_from_project(root)), ensure_ascii=False))


@cli.command()
@click.option('--notify', is_flag=True, help='将事实包发送给独立 Codex B 会话')
@click.option('--json-output', is_flag=True)
@click.pass_obj
def audit(root, notify, json_output):
    """审计当前最后一次提交。"""
    from archguard.runtime import audit_project
    from archguard.core.report_generator import generate_report
    from archguard.project_control import status, require
    if notify and status(root)['status'] != 'enabled':
        click.echo('IDE_Audit 未开启或暂停，本次提交不触发审计。')
        return
    execute(lambda: require(root))
    result = execute(lambda: audit_project(root))
    if notify:
        from archguard.dispatch_queue import enqueue
        queued = execute(lambda: enqueue(root, result.audit_id))
        # 入队先于终端展示；Hook 默认仅给摘要，完整报告已在本地封存。
        if json_output:
            click.echo(result.model_dump_json(indent=2))
        else:
            click.echo(json.dumps({'audit_id':result.audit_id, 'analysis_status':result.analysis_status,
                                   'queue_status':queued['status']}, ensure_ascii=True))
    else:
        click.echo(result.model_dump_json(indent=2) if json_output else generate_report(result.model_dump(mode='json')))


@cli.command()
@click.argument('text')
@click.pass_obj
def prompt(root, text):
    """手动记录一条原始需求。"""
    from archguard.sync.prompts import record_prompt
    click.echo(json.dumps(execute(lambda: record_prompt(root, text)), ensure_ascii=False))


@cli.command('prepare')
@click.pass_obj
def prepare(root):
    """提交前固定暂存树和需求/申报批次。"""
    from archguard.runtime import prepare_commit
    click.echo(json.dumps(execute(lambda: prepare_commit(root)), ensure_ascii=False))


@cli.command()
@click.option('-m', '--message', required=True)
@click.argument('paths', nargs=-1, type=click.Path())
@click.pass_obj
def commit(root, message, paths):
    """暂存指定路径后提交；不提供路径时只提交当前暂存区。"""
    import git
    from archguard.runtime import prepare_commit, audit_project
    def perform():
        repo = git.Repo(root)
        if paths:
            for path in paths:
                target = (root / path).resolve()
                if not target.is_relative_to(root):
                    raise ValueError('提交路径超出工程')
            repo.git.add('--', *paths)
        prepare_commit(root)
        repo.git.commit('-m', message)
        return audit_project(root)
    result = execute(perform)
    click.echo('提交与本地分析完成: ' + result.commit_hash)


@cli.command()
@click.pass_obj
def graph(root):
    """只读显示工作态代码图谱。"""
    from archguard.sync.graph import GraphManager
    click.echo(execute(lambda: GraphManager(root).read_graph().model_dump_json(by_alias=True, indent=2)))


@cli.command()
@click.option('--limit', type=click.IntRange(1, 1000), default=10)
@click.pass_obj
def history(root, limit):
    """显示审计结果历史，区别于开发操作账本。"""
    from archguard.storage import metadata_path, read_json
    def read_history():
        path = metadata_path(root, 'results', 'history')
        values = [read_json(f) for f in path.glob('*.json')]
        return sorted(values, key=lambda x: x['timestamp'], reverse=True)[:limit]
    for result in execute(read_history):
        click.echo(f"{result['commit_hash']} {result['analysis_status']} {result['commit_message']}")


@cli.command()
@click.option('--audit-id', default=None, help='已封存任务的完整提交 SHA')
@click.pass_obj
def recover(root, audit_id):
    """从原 B 轮次恢复裁决，不重复派发。"""
    from archguard.runtime import get_result
    from archguard.adapters.codex.session_manager import CodexSessionManager
    click.echo(json.dumps(execute(lambda: CodexSessionManager(root).recover(get_result(root, audit_id))), ensure_ascii=False))


@cli.command()
@click.argument('question')
@click.option('--audit-id', default=None, help='已封存任务的完整提交 SHA')
@click.pass_obj
def ask(root, question, audit_id):
    """向原 B 会话发起只读追问。"""
    from archguard.runtime import get_result
    from archguard.adapters.codex.session_manager import CodexSessionManager
    click.echo(execute(lambda: CodexSessionManager(root).ask(get_result(root, audit_id), question)))





@cli.command('queue-status')
@click.option('--audit-id', default=None)
@click.pass_obj
def queue_status(root, audit_id):
    """显示当前提交的后台派发与 B 会话标识。"""
    from archguard.runtime import get_result
    from archguard.dispatch_queue import status
    click.echo(json.dumps(execute(lambda: status(root, audit_id or get_result(root).audit_id)), ensure_ascii=False))


@cli.command('drain')
@click.pass_obj
def drain_queue(root):
    """串行处理已封存的队列，不扩大审计范围。"""
    from archguard.dispatch_queue import drain
    execute(lambda: drain(root))


@cli.command('retry-audit')
@click.option('--audit-id', required=True)
@click.pass_obj
def retry_audit(root, audit_id):
    """核验原轮次后恢复失败队列，不盲目重复发送。"""
    from archguard.dispatch_queue import retry
    click.echo(json.dumps(execute(lambda: retry(root, audit_id)), ensure_ascii=False))


@cli.command('decline')
@click.option('--confirmed', is_flag=True, help='用户已明确拒绝当前项目自动审计')
@click.pass_obj
def decline_command(root, confirmed):
    if not confirmed:
        raise click.ClickException('需要用户明确拒绝，不能代替用户选择')
    from archguard.adapters.codex.session_manager import CodexSessionManager
    from archguard.project_control import choose
    def perform():
        manager = CodexSessionManager(root)
        with manager.client_factory() as client:
            project_id = manager._project_id(client)
        return choose(root, project_id, False, confirmed=True)
    click.echo(json.dumps(execute(perform), ensure_ascii=False))


@cli.command('project-status')
@click.pass_obj
def project_status(root):
    from archguard.project_control import status
    click.echo(json.dumps(status(root), ensure_ascii=False))


@cli.command('pause')
@click.pass_obj
def pause_command(root):
    from archguard.project_control import pause
    click.echo(json.dumps(execute(lambda: pause(root)), ensure_ascii=False))


@cli.command('resume')
@click.pass_obj
def resume_command(root):
    from archguard.project_control import resume
    click.echo(json.dumps(execute(lambda: resume(root)), ensure_ascii=False))


@cli.command('usage')
@click.pass_obj
def usage_command(root):
    from archguard.usage import refresh_current
    click.echo(json.dumps(execute(lambda: refresh_current(root)), ensure_ascii=False))


@cli.command('operation-usage')
@click.option('--limit', default=10, type=click.IntRange(1, 20))
@click.option('--before', default=None)
@click.pass_obj
def operation_usage_command(root, limit, before):
    """分页查看本地环节用量日志，不调用模型。"""
    from archguard.operation_log import read
    click.echo(json.dumps(execute(lambda: read(root, limit, before)), ensure_ascii=False))


if __name__ == '__main__':
    cli()
