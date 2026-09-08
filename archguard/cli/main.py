"""统一命令入口，失败始终使用非零退出状态。"""
import json
from pathlib import Path
import click
from archguard import __version__


@click.group()
@click.version_option(__version__)
@click.option('--project-root', type=click.Path(exists=True, file_okay=False, path_type=Path), default='.')
@click.pass_context
def cli(ctx, project_root):
    """IDE_Audit：协同维护、提交事实与独立审计。"""
    ctx.obj = project_root.resolve()


def execute(action):
    try:
        return action()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@cli.command()
@click.option('--ide', default='codex-desktop', type=click.Choice(['codex', 'codex-desktop']))
@click.pass_obj
def install(root, ide):
    """安装统一守则、MCP 与提交 Hook。"""
    from archguard.adapters.codex.installer import install_to_project
    click.echo(json.dumps(execute(lambda: install_to_project(root, ide)), ensure_ascii=False))


@cli.command()
@click.pass_obj
def uninstall(root):
    """卸载插件管理的入口，保留历史数据。"""
    from archguard.adapters.codex.installer import uninstall_from_project
    click.echo(json.dumps(execute(lambda: uninstall_from_project(root)), ensure_ascii=False))


@cli.command()
@click.option('--notify', is_flag=True, help='将事实包发送给独立 Codex B 会话')
@click.option('--json-output', is_flag=True)
@click.pass_obj
def audit(root, notify, json_output):
    """审计当前最后一次提交。"""
    from archguard.runtime import audit_project
    from archguard.core.report_generator import generate_report
    result = execute(lambda: audit_project(root))
    click.echo(result.model_dump_json(indent=2) if json_output else generate_report(result.model_dump(mode='json')))
    if notify:
        from archguard.adapters.codex.session_manager import CodexSessionManager
        execute(lambda: CodexSessionManager(root).audit(result))


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
@click.option('--dry-run', is_flag=True)
@click.pass_obj
def migrate(root, dry_run):
    """校验并迁移旧 .ai-sync 资产。"""
    from archguard.sync.migration import migrate_assets
    click.echo(json.dumps(execute(lambda: migrate_assets(root, dry_run)), ensure_ascii=False, indent=2))


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


if __name__ == '__main__':
    cli()
