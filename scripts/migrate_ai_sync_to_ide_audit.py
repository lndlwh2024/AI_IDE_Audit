"""兼容旧迁移脚本入口，统一委托到已验证的插件迁移逻辑。"""
import json
import click
from archguard.sync.migration import migrate_assets


@click.command()
@click.option('--project-root', default='.', type=click.Path(exists=True, file_okay=False))
@click.option('--dry-run', is_flag=True)
def migrate(project_root, dry_run):
    try:
        click.echo(json.dumps(migrate_assets(project_root, dry_run), ensure_ascii=False, indent=2))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


if __name__ == '__main__':
    migrate()
