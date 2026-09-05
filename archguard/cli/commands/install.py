import click
import os
from archguard.adapters.codex.installer import install_to_project

@click.command()
@click.option('--ide', default='codex-desktop', help='目标 IDE 类型')
def install(ide):
    """安装 IDE_Audit"""
    project_root = os.getcwd()
    click.echo(f"安装 IDE_Audit 到 {project_root} (IDE: {ide})")
    install_to_project(project_root, ide)
    click.echo("安装完成")
