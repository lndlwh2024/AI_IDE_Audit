import click
import subprocess

@click.command()
@click.option('-m', '--message', required=True, help='提交信息')
def commit(message):
    """提交并审计"""
    click.echo("执行 git commit...")
    try:
        subprocess.run(["git", "commit", "-m", message], check=True)
        # hook 会自动触发 audit
    except subprocess.CalledProcessError as e:
        click.echo(f"提交失败: {e}", err=True)
