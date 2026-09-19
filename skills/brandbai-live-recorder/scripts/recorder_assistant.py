"""Customer-facing Windows launcher for the BrandBAI live recorder service."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Sequence


ASSISTANT_VERSION = "0.22.16"
SERVICE_NAME = "brandbai-live-recorder"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SERVICE_PORTS = (8765, 18765, 28765)
CUSTOM_PROTOCOL = "brandbai-recorder"
CUSTOM_PROTOCOL_URL = f"{CUSTOM_PROTOCOL}://start"
BRANDED_LAUNCHER_NAME = "BrandBAI直播采集助手.exe"
START_MENU_NAME = "BrandBAI 直播采集助手.url"
LEGACY_START_MENU_NAME = "BrandBAI 直播录屏助手.url"
LAUNCHER_CONFIG_NAME = "launcher.cfg"


def application_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_private_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "BrandBAI" / "LiveRecorder"
    return Path.home() / ".brandbai" / "live-recorder"


def default_output_root() -> Path:
    profile = Path(os.environ.get("USERPROFILE") or Path.home())
    return profile / "Videos" / "BrandBAI直播录屏"


def health_url(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> str:
    return f"http://{host}:{port}/v1/health"


def probe_service(
    *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout_seconds: float = 1.5
) -> dict[str, object]:
    try:
        request = urllib.request.Request(
            health_url(host, port), headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return {"status": "occupied"}
    except urllib.error.URLError:
        return {"status": "offline"}
    except (OSError, ValueError, UnicodeDecodeError):
        return {"status": "occupied"}

    if payload.get("service") != SERVICE_NAME:
        return {"status": "occupied"}
    if payload.get("status") != "ready":
        return {"status": "starting", "service_version": payload.get("version")}
    return {"status": "ready", "service_version": payload.get("version")}


def build_service_command(
    *,
    app_root: Path,
    state_dir: Path,
    output_root: Path,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> list[str]:
    service_script = app_root / "scripts" / "run_local_service.py"
    if not service_script.is_file():
        raise FileNotFoundError("采集助手文件不完整")
    return [
        sys.executable,
        "-B",
        str(service_script),
        "serve",
        "--state-dir",
        str(state_dir),
        "--output-root",
        str(output_root),
        "--host",
        host,
        "--port",
        str(port),
    ]


def _spawn_service(command: list[str], *, working_dir: Path, log_file: Path) -> subprocess.Popen:
    creationflags = 0
    startupinfo = None
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

    log_handle = log_file.open("ab")
    try:
        return subprocess.Popen(
            command,
            cwd=str(working_dir),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            creationflags=creationflags,
            startupinfo=startupinfo,
            start_new_session=os.name != "nt",
        )
    finally:
        log_handle.close()


def start_assistant(
    *,
    app_root: Path | None = None,
    state_dir: Path | None = None,
    output_root: Path | None = None,
    host: str = DEFAULT_HOST,
    port: int | None = None,
    wait_seconds: float = 20.0,
    probe: Callable[..., dict[str, object]] = probe_service,
    spawn: Callable[..., subprocess.Popen] = _spawn_service,
) -> dict[str, object]:
    if host != DEFAULT_HOST:
        return {"status": "blocked", "reason": "loopback_only"}
    if port is not None and (port < 1 or port > 65535):
        return {"status": "blocked", "reason": "invalid_port"}

    candidate_ports = (port,) if port is not None else SERVICE_PORTS
    first_offline_port: int | None = None
    first_starting_port: int | None = None
    for candidate_port in candidate_ports:
        current = probe(host=host, port=candidate_port)
        if current.get("status") == "ready":
            return {
                "status": "ready",
                "already_running": True,
                "service_version": current.get("service_version"),
                "service_port": candidate_port,
            }
        if current.get("status") == "starting" and first_starting_port is None:
            first_starting_port = candidate_port
        if current.get("status") == "offline" and first_offline_port is None:
            first_offline_port = candidate_port

    selected_port = first_starting_port or first_offline_port
    if selected_port is None:
        return {"status": "blocked", "reason": "local_ports_unavailable"}

    root = (app_root or application_root()).resolve()
    private_root = default_private_root()
    state = (state_dir or (private_root / "state")).expanduser().resolve()
    output = (output_root or default_output_root()).expanduser().resolve()
    try:
        logs = (state.parent if state_dir is not None else private_root) / "logs"
        state.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True)
        process = None
        if first_starting_port is None:
            command = build_service_command(
                app_root=root,
                state_dir=state,
                output_root=output,
                host=host,
                port=selected_port,
            )
            process = spawn(
                command,
                working_dir=root / "scripts",
                log_file=logs / "assistant.log",
            )
    except (OSError, ValueError):
        return {"status": "failed", "reason": "assistant_start_failed"}

    deadline = time.monotonic() + max(0.0, wait_seconds)
    while time.monotonic() < deadline:
        current = probe(host=host, port=selected_port)
        if current.get("status") == "ready":
            return {
                "status": "ready",
                "already_running": first_starting_port is not None,
                "service_version": current.get("service_version"),
                "service_port": selected_port,
                "process_id": getattr(process, "pid", None),
            }
        if current.get("status") == "occupied":
            return {"status": "blocked", "reason": "local_port_unavailable"}
        if process is not None and process.poll() is not None:
            return {"status": "failed", "reason": "assistant_start_failed"}
        time.sleep(0.25)

    return {
        "status": "starting",
        "service_port": selected_port,
        "process_id": getattr(process, "pid", None),
    }


def _pythonw_path() -> Path:
    executable = Path(sys.executable).resolve()
    candidate = executable.with_name("pythonw.exe")
    return candidate if candidate.is_file() else executable


def _protocol_command(launcher_executable: Path) -> str:
    return f'"{launcher_executable}" "%1"'


def _powershell_path() -> Path:
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if not executable:
        raise FileNotFoundError("Windows launcher compiler is unavailable")
    return Path(executable).resolve()


def _compile_branded_launcher(installed_root: Path) -> Path:
    assets = installed_root / "assets" / "windows-assistant"
    source = assets / "BrandBAIRecorderLauncher.cs"
    compiler = assets / "compile_launcher.ps1"
    if not source.is_file() or not compiler.is_file():
        raise FileNotFoundError("采集助手安装文件不完整")

    launcher = installed_root / BRANDED_LAUNCHER_NAME
    staged = installed_root / f".{Path(BRANDED_LAUNCHER_NAME).stem}.new.exe"
    if staged.is_file():
        staged.unlink()
    completed = subprocess.run(
        [
            str(_powershell_path()),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(compiler),
            "-SourcePath",
            str(source),
            "-OutputPath",
            str(staged),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
    )
    if completed.returncode != 0 or not staged.is_file():
        if staged.is_file():
            staged.unlink()
        raise OSError("BrandBAI launcher compilation failed")
    os.replace(staged, launcher)
    return launcher


def _write_launcher_config(installed_root: Path, installed_script: Path) -> Path:
    config = installed_root / LAUNCHER_CONFIG_NAME
    staged = installed_root / f".{LAUNCHER_CONFIG_NAME}.new"
    staged.write_text(
        f"{_pythonw_path()}\n{installed_script}\n",
        encoding="utf-8",
    )
    os.replace(staged, config)
    return config


def _copy_application(source_root: Path, destination_root: Path) -> Path:
    source = source_root.resolve()
    destination = destination_root.resolve()
    if source != destination:
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source,
            destination,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "test_*.py"),
        )
    return destination


def _is_owned_shortcut(shortcut: Path) -> bool:
    try:
        lines = shortcut.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return False
    urls = [line.strip()[4:] for line in lines if line.strip().startswith("URL=")]
    return urls == [CUSTOM_PROTOCOL_URL] and "[InternetShortcut]" in lines


def _write_start_menu_shortcut() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    programs = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True, exist_ok=True)
    shortcut = programs / START_MENU_NAME
    if shortcut.exists() and not _is_owned_shortcut(shortcut):
        raise OSError("The assistant shortcut name is already in use")
    shortcut.write_text(
        f"[InternetShortcut]\nURL={CUSTOM_PROTOCOL_URL}\n",
        encoding="utf-8-sig",
    )
    legacy = programs / LEGACY_START_MENU_NAME
    if _is_owned_shortcut(legacy):
        legacy.unlink()
    return shortcut


def install_windows_assistant() -> dict[str, object]:
    if os.name != "nt":
        return {"status": "unsupported", "reason": "windows_only"}

    import winreg

    try:
        install_root = default_private_root() / "app"
        installed_root = _copy_application(application_root(), install_root)
        installed_script = installed_root / "scripts" / "recorder_assistant.py"
        launcher = _compile_branded_launcher(installed_root)
        _write_launcher_config(installed_root, installed_script)

        base_key = rf"Software\Classes\{CUSTOM_PROTOCOL}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_key) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "URL:BrandBAI 直播采集助手")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_key + r"\DefaultIcon") as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, f'"{launcher}",0')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_key + r"\shell\open\command") as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, _protocol_command(launcher))

        _write_start_menu_shortcut()
        service = start_assistant(app_root=installed_root)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"status": "failed", "reason": "assistant_install_failed"}
    return {
        "status": "installed",
        "service_status": service.get("status"),
        "restart_applies_update": bool(
            service.get("already_running")
            and service.get("service_version")
            and service.get("service_version") != ASSISTANT_VERSION
        ),
    }


def _delete_registry_tree(winreg_module, root, path: str) -> None:
    try:
        with winreg_module.OpenKey(root, path, 0, winreg_module.KEY_READ | winreg_module.KEY_WRITE) as key:
            children: list[str] = []
            index = 0
            while True:
                try:
                    children.append(winreg_module.EnumKey(key, index))
                    index += 1
                except OSError:
                    break
        for child in children:
            _delete_registry_tree(winreg_module, root, path + "\\" + child)
        winreg_module.DeleteKey(root, path)
    except FileNotFoundError:
        return


def uninstall_windows_assistant() -> dict[str, object]:
    if os.name != "nt":
        return {"status": "unsupported", "reason": "windows_only"}

    import winreg

    _delete_registry_tree(
        winreg,
        winreg.HKEY_CURRENT_USER,
        rf"Software\Classes\{CUSTOM_PROTOCOL}",
    )
    appdata = os.environ.get("APPDATA")
    if appdata:
        programs = (
            Path(appdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
        )
        for name in (START_MENU_NAME, LEGACY_START_MENU_NAME):
            shortcut = programs / name
            if _is_owned_shortcut(shortcut):
                shortcut.unlink()
    return {"status": "uninstalled", "recordings_preserved": True}


def _valid_protocol_request(value: str | None) -> bool:
    if value is None:
        return True
    return value.rstrip("/").lower() == CUSTOM_PROTOCOL_URL.rstrip("/").lower()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BrandBAI 直播采集助手")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="启动采集助手")
    start.add_argument("--quiet", action="store_true")
    start.add_argument("--json", action="store_true")
    start.add_argument("--state-dir", type=Path)
    start.add_argument("--output-root", type=Path)
    start.add_argument("--host", default=DEFAULT_HOST)
    start.add_argument("--port", type=int)
    start.add_argument("--wait-seconds", default=20.0, type=float)
    start.add_argument("request_uri", nargs="?")

    status = subparsers.add_parser("status", help="检查采集助手")
    status.add_argument("--json", action="store_true")
    status.add_argument("--host", default=DEFAULT_HOST)
    status.add_argument("--port", type=int)

    install = subparsers.add_parser("install-windows", help="首次安装 Windows 采集助手")
    install.add_argument("--json", action="store_true")

    uninstall = subparsers.add_parser("uninstall-windows", help="移除 Windows 启动入口")
    uninstall.add_argument("--json", action="store_true")
    return parser


def _customer_message(result: dict[str, object]) -> str:
    status = result.get("status")
    if status == "ready":
        return "采集助手已准备好，请返回浏览器选择录制或资料采集。"
    if status == "starting":
        return "采集助手正在启动，请返回浏览器稍候。"
    if status == "installed":
        if result.get("restart_applies_update"):
            return "安装完成。当前采集助手仍可使用，更新将在下次启动时生效。"
        return "安装完成，采集助手已准备好。"
    if status == "uninstalled":
        return "启动入口已移除，已有文件不会被删除。"
    if status == "offline":
        return "采集助手尚未启动。"
    if status == "unsupported":
        return "当前安装入口仅支持 Windows。"
    return "采集助手暂时无法启动，请重新运行安装程序。"


def _emit(result: dict[str, object], *, as_json: bool, quiet: bool = False) -> None:
    if quiet:
        return
    if as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(_customer_message(result))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "start":
        if not _valid_protocol_request(args.request_uri):
            result = {"status": "blocked", "reason": "unsupported_request"}
        else:
            result = start_assistant(
                state_dir=args.state_dir,
                output_root=args.output_root,
                host=args.host,
                port=args.port,
                wait_seconds=args.wait_seconds,
            )
        _emit(result, as_json=args.json, quiet=args.quiet)
    elif args.command == "status":
        if args.port is not None:
            result = probe_service(host=args.host, port=args.port)
        else:
            result = {"status": "offline"}
            for candidate_port in SERVICE_PORTS:
                current = probe_service(host=args.host, port=candidate_port)
                if current.get("status") == "ready":
                    result = {**current, "service_port": candidate_port}
                    break
        _emit(result, as_json=args.json)
    elif args.command == "install-windows":
        result = install_windows_assistant()
        _emit(result, as_json=args.json)
    elif args.command == "uninstall-windows":
        result = uninstall_windows_assistant()
        _emit(result, as_json=args.json)
    else:
        result = {"status": "blocked", "reason": "unsupported_command"}
        _emit(result, as_json=False)
    return 0 if result.get("status") in {"ready", "starting", "installed", "uninstalled"} else 2


if __name__ == "__main__":
    sys.exit(main())
