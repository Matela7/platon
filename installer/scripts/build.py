"""Native, repeatable desktop build. Run from any working directory."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "installer"


def run(*args: str, cwd: Path = ROOT) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def target() -> tuple[str, str]:
    system, machine = platform.system(), platform.machine().lower()
    if system == "Windows" and machine in {"amd64", "x86_64"}:
        return "win", "x64"
    if system == "Darwin" and machine == "arm64":
        if int(platform.mac_ver()[0].split(".")[0]) < 14:
            raise SystemExit("macOS 14+ required")
        return "mac", "arm64"
    if system == "Linux" and machine in {"amd64", "x86_64"}:
        libc, version = platform.libc_ver()
        if libc != "glibc" or tuple(map(int, version.split(".")[:2])) < (2, 28):
            raise SystemExit("Linux glibc >=2.28 required")
        return "linux", "x64"
    raise SystemExit(f"Unsupported native platform: {system}/{machine}. Intel macOS and Windows ARM are not supported.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-backend", action="store_true", help="Reuse existing backend and Python staging")
    parser.add_argument("--dir", action="store_true", help="Build unpacked application for local smoke test")
    args = parser.parse_args()
    os_target, arch = target()
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm or not shutil.which("uv"):
        raise SystemExit("Install Node.js/npm and uv first")
    staging = INSTALLER / "staging"
    staging.mkdir(exist_ok=True)
    os.environ["UV_PROJECT_ENVIRONMENT"] = str(INSTALLER / ".venv")
    if not args.skip_backend:
        run("uv", "python", "install", "3.13")
        run("uv", "sync", "--frozen", "--no-dev", "--python", "3.13")
        run("uv", "run", "--frozen", "--no-dev", "--with-requirements", str(INSTALLER / "backend" / "requirements-build.txt"), "python", "-m", "PyInstaller", "--clean", "--noconfirm", "--distpath", str(staging / "backend"), "--workpath", str(INSTALLER / "backend" / "build"), str(INSTALLER / "backend" / "platon-backend.spec"))
        interpreter = Path(subprocess.check_output(["uv", "python", "find", "--managed-python", "3.13"], text=True).strip()).resolve()
        python_root = interpreter.parent if os.name == "nt" else interpreter.parent.parent
        python_staging = staging / "python"
        if python_staging.exists():
            if python_staging.resolve().parent != staging.resolve():
                raise SystemExit("Refusing to replace Python outside installer/staging")
            shutil.rmtree(python_staging)
        shutil.copytree(python_root, python_staging, symlinks=True)
        (staging / "target.json").write_text(json.dumps([os_target, arch]), encoding="utf-8")
    elif not (staging / "target.json").is_file() or json.loads((staging / "target.json").read_text(encoding="utf-8")) != [os_target, arch]:
        raise SystemExit("Staged backend target differs from this machine. Rebuild without --skip-backend.")
    backend_bundle = staging / "backend"
    if os_target == "linux":
        backend_bundle /= "platon-backend"
    executable = backend_bundle / ("platon-backend.exe" if os.name == "nt" else "platon-backend")
    if not executable.is_file() or not (staging / "python").is_dir() or (os_target == "linux" and not (backend_bundle / "_internal").is_dir()):
        raise SystemExit("Missing staged backend/Python. Run without --skip-backend first.")
    os.environ["PLATON_PYTHON_EXECUTABLE"] = str(staging / "python" / ("python.exe" if os.name == "nt" else "bin/python3.13"))
    run(str(executable), "--self-test")
    app_staging = staging / "app"
    if app_staging.exists():
        if app_staging.resolve().parent != staging.resolve():
            raise SystemExit("Refusing to replace staging outside installer/staging")
        shutil.rmtree(app_staging)
    shutil.copytree(ROOT / "platon_frontend", app_staging,
                    ignore=shutil.ignore_patterns("node_modules", "dist", ".git"))
    manifest_path = app_staging / "package.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # electron-builder's two-package layout keeps configuration in installer/.
    manifest.pop("build", None)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    run(npm, "ci", cwd=staging / "app")
    run(npm, "ci", cwd=INSTALLER)
    command = [npm, "exec", "--", "electron-builder", "--config", "electron-builder.cjs", f"--{os_target}", f"--{arch}", "--publish", "never"]
    if args.dir:
        command.append("--dir")
    run(*command, cwd=INSTALLER)


if __name__ == "__main__":
    main()
