import click
import os
from archguard.core.ledger_analyzer import LedgerAnalyzer

@click.command()
def history():
    """查看审计历史"""
    project_root = os.getcwd()
    try:
        la = LedgerAnalyzer(project_root)
        records = la.get_recent_records(10)
        click.echo("最近的审计记录:")
        for r in records:
            click.echo(r)
    except Exception as e:
        click.echo(f"获取历史失败: {e}", err=True)
