import click
import os
from archguard.core.engine import AuditEngine

@click.command()
def audit():
    """手动触发审计"""
    project_root = os.getcwd()
    click.echo("开始审计...")
    engine = AuditEngine(project_root)
    try:
        report = engine.generate_report()
        click.echo("审计报告生成完成。")
    except Exception as e:
        click.echo(f"审计失败: {e}", err=True)
