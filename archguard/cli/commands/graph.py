import click
import os
from archguard.core.graph_analyzer import GraphAnalyzer

@click.command()
def graph():
    """查看图谱摘要"""
    project_root = os.getcwd()
    try:
        ga = GraphAnalyzer(project_root)
        summary = ga.get_summary()
        click.echo("图谱摘要:")
        click.echo(summary)
    except Exception as e:
        click.echo(f"获取图谱失败: {e}", err=True)
