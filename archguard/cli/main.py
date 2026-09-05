import click
from .commands.install import install
from .commands.audit import audit
from .commands.commit import commit
from .commands.graph import graph
from .commands.history import history

@click.group()
def cli():
    """IDE_Audit 命令行工具"""
    pass

cli.add_command(install)
cli.add_command(audit)
cli.add_command(commit)
cli.add_command(graph)
cli.add_command(history)

if __name__ == '__main__':
    cli()
