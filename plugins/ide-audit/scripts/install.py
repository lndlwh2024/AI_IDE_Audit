"""从随插件提供的 wheel 安装项目隔离运行环境及入口。"""
import argparse
import subprocess
import sys
import venv
from pathlib import Path


def install(project_root):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.version_info < (3, 11):
        raise RuntimeError('需要 Python 3.11 或更新版本')
    root = Path(project_root).resolve(strict=True)
    wheels = list((Path(__file__).resolve().parents[1] / 'wheels').glob('ide_audit-*.whl'))
    if len(wheels) != 1:
        raise RuntimeError('插件必须包含唯一 IDE_Audit wheel，请使用完整发布包')
    base = root / '.ide_audit'
    if base.is_symlink() or (base.exists() and base.resolve() != base):
        raise RuntimeError('审计目录不能重定向')
    runtime = base / 'runtime'
    if runtime.is_symlink() or (runtime.exists() and runtime.resolve() != runtime):
        raise RuntimeError('运行环境不能重定向')
    venv.EnvBuilder(with_pip=True).create(runtime)
    python = runtime / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    subprocess.run([str(python), '-m', 'pip', 'install', str(wheels[0])], check=True)
    subprocess.run([str(python), '-m', 'archguard.cli.main', '--project-root', str(root), 'install'], check=True)
    print('项目接入完成。重新打开 A 任务加载 MCP，然后立即建立或刷新图谱。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-root', required=True)
    install(parser.parse_args().project_root)
