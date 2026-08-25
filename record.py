import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from har_env import HAR_OUTPUT_PATH_ENV_VAR

MITMDUMP_HEALTH_CHECK_TIMEOUT_SECONDS = 10.0
MITMDUMP_HEALTH_CHECK_INTERVAL_SECONDS = 0.2
MITMDUMP_TERMINATE_TIMEOUT_SECONDS = 5.0
BODYLESS_STATUS = {101, 204, 304}


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
        probe_socket.bind(("127.0.0.1", 0))
        return probe_socket.getsockname()[1]


def resolve_mitmdump_path():
    executable_name = "mitmdump.exe" if sys.platform == "win32" else "mitmdump"
    return Path(sys.executable).parent / executable_name


def start_mitmdump(port, output_path, addon_path):
    env = dict(os.environ)
    env[HAR_OUTPUT_PATH_ENV_VAR] = str(output_path)
    process = subprocess.Popen(
        [str(resolve_mitmdump_path()), "--listen-port", str(port), "-s", str(addon_path), "--set", "termlog_verbosity=warn"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_until_ready(port)
    return process


def wait_until_ready(port):
    deadline = time.monotonic() + MITMDUMP_HEALTH_CHECK_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return
        except OSError:
            time.sleep(MITMDUMP_HEALTH_CHECK_INTERVAL_SECONDS)
    raise RuntimeError(f"mitmdump não respondeu na porta {port} depois de {MITMDUMP_HEALTH_CHECK_TIMEOUT_SECONDS}s.")


def stop_mitmdump(process):
    process.terminate()
    try:
        process.wait(timeout=MITMDUMP_TERMINATE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def audit_har(output_path):
    try:
        entries = json.loads(output_path.read_text(encoding="utf-8"))["log"]["entries"]
    except Exception as e:
        print(f"  Erro: não foi possível auditar o HAR ({e})")
        return

    sem_corpo = []
    for index, entry in enumerate(entries):
        response = entry["response"]
        if response.get("content", {}).get("text"):
            continue
        if response.get("status") in BODYLESS_STATUS:
            continue
        sem_corpo.append((index, entry["request"]["method"], response.get("status"), entry["request"]["url"]))

    print()
    print("=" * 50)
    print("  Auditoria de completude")
    print("=" * 50)
    print(f"  entries                : {len(entries)}")
    print(f"  com corpo gravado      : {len(entries) - len(sem_corpo)}")
    print(f"  sem corpo (inesperado) : {len(sem_corpo)}")
    print("=" * 50)

    if not sem_corpo:
        print("  HAR completo: toda resposta esperada teve o corpo gravado.")
        print()
        return

    print("  As respostas abaixo não tiveram corpo gravado:")
    for index, method, status, url in sem_corpo:
        print(f"    entry {index:>4}  {method:<6}{status:>5}  {url}")
    print()


def main():
    url = "https://autorizador.unimedriopreto.com.br/PlanodeSaude/"
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"captura_{datetime.now().strftime('%Y%m%d_%H%M%S')}.har"
    addon_path = Path(__file__).resolve().parent / "har_addon.py"
    port = free_port()

    print("=" * 50)
    print("  HAR Recorder (via mitmproxy)")
    print("=" * 50)
    print(f"  URL inicial : {url}")
    print(f"  Proxy       : 127.0.0.1:{port}")
    print(f"  Output      : {output_path}")
    print("=" * 50)
    print()

    mitmdump_process = start_mitmdump(port, output_path, addon_path)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=["--disable-quic"])
            context = browser.new_context(
                proxy={"server": f"http://127.0.0.1:{port}"},
                ignore_https_errors=True,
                service_workers="block",
            )
            page = context.new_page()

            browser_closed = False

            def on_disconnected():
                nonlocal browser_closed
                browser_closed = True

            browser.on("disconnected", on_disconnected)

            try:
                page.goto(url)
            except Exception as e:
                print(f"  Aviso: {e}")

            print("  Navegador aberto! Navegue à vontade.")
            print()
            print("  Para finalizar: Ctrl+C no terminal ou feche o navegador.")
            print()

            try:
                while not browser_closed:
                    try:
                        page.wait_for_timeout(500)
                    except Exception:
                        break
            except KeyboardInterrupt:
                pass

            print()
            print("  Finalizando...")

            if not browser_closed:
                try:
                    page.wait_for_load_state("networkidle")
                except Exception:
                    pass

            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
    finally:
        stop_mitmdump(mitmdump_process)

    if output_path.exists():
        size_kb = output_path.stat().st_size / 1024
        print(f"  HAR gravado com sucesso!")
        print(f"  Arquivo : {output_path}")
        print(f"  Tamanho : {size_kb:.1f} KB")
        audit_har(output_path)
    else:
        print("  Erro: HAR não foi gerado.")
        print()


if __name__ == "__main__":
    main()
