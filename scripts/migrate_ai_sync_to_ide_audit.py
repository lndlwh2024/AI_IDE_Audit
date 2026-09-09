"""外部迁移入口；单独下载运行，不随插件发布或被插件调用。"""
import json
import click
from legacy_sync_assets import migrate_assets


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
