"""从干净暂存源码构建 wheel 与统一插件，外部迁移工具单独打包。"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def build():
    root = Path(__file__).resolve().parents[1]
    output = root / 'dist'
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ide-audit-release-') as temp:
        stage = Path(temp)
        source = stage / 'source'; source.mkdir()
        shutil.copytree(root / 'archguard', source / 'archguard', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name in ('pyproject.toml','README.md','LICENSE'):
            shutil.copy2(root / name, source / name)
        subprocess.run([sys.executable,'-m','pip','wheel',str(source),'--no-deps','--no-build-isolation','--wheel-dir',str(stage/'wheels')],check=True)
        wheel = next((stage/'wheels').glob('*.whl'))
        with zipfile.ZipFile(wheel) as archive:
            if any('migration.py' in n or n.startswith('scripts/') for n in archive.namelist()):
                raise RuntimeError('插件 wheel 混入迁移代码')
        plugin = stage / 'ide-audit'
        shutil.copytree(root/'plugins/ide-audit',plugin,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        (plugin/'wheels').mkdir(exist_ok=True)
        shutil.copy2(wheel, plugin/'wheels'/wheel.name)
        version = json.loads((plugin/'.codex-plugin/plugin.json').read_text(encoding='utf-8'))['version']
        plugin_zip = output/f'ide-audit-{version}-plugin.zip'
        with zipfile.ZipFile(plugin_zip,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(plugin.rglob('*')):
                if path.is_file(): archive.write(path,path.relative_to(stage).as_posix())
        migration_zip=output/f'ide-audit-{version}-project-switch.zip'
        with zipfile.ZipFile(migration_zip,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in ('switch_project.py','legacy_sync_assets.py','migrate_ai_sync_to_ide_audit.py','README.md'):
                archive.write(root/'scripts'/name,name)
        shutil.copy2(wheel,output/wheel.name)
        files=[plugin_zip,migration_zip,output/wheel.name]
        (output/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in files),encoding='utf-8')
        print('发布文件：'+', '.join(p.name for p in files))


if __name__ == '__main__': build()
