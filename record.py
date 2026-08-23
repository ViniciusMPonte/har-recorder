import base64
import json
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

INTERCEPT_URL_PATTERN = "**/*"
SKIP_RESOURCE_TYPES = {"media", "websocket", "eventsource"}
CONDITIONAL_HEADERS = ("if-none-match", "if-modified-since")
BODYLESS_STATUS = {101, 204, 304}
CDP_TOTAL_BUFFER = 1024 * 1024 * 1024
CDP_RESOURCE_BUFFER = 256 * 1024 * 1024


def should_intercept(request):
    if request.resource_type in SKIP_RESOURCE_TYPES:
        return False

    headers = {name.lower() for name in request.headers}
    return not any(name in headers for name in CONDITIONAL_HEADERS)


def upstream_headers(request):
    return {
        name: value
        for name, value in request.all_headers().items()
        if name.lower() != "accept-encoding"
    }


def make_route_handler(api_context, capturados, stats):
    def handler(route):
        request = route.request
        if not should_intercept(request):
            stats["ignoradas"] += 1
            route.continue_()
            return

        try:
            response = api_context.fetch(
                request.url,
                method=request.method,
                headers=upstream_headers(request),
                data=request.post_data_buffer,
                max_redirects=0,
            )
            body = response.body()
        except Exception:
            stats["fallback"] += 1
            try:
                route.continue_()
            except Exception:
                pass
            return

        stats["interceptadas"] += 1
        capturados.setdefault((request.method, request.url), []).append((response.status, body))
        try:
            route.fulfill(response=response, body=body)
        except Exception:
            stats["fallback"] += 1

    return handler


def inject_captured_bodies(output_path, capturados):
    documento = json.loads(output_path.read_text(encoding="utf-8"))
    pendentes = {chave: list(corpos) for chave, corpos in capturados.items()}
    injetados = 0

    for entry in documento["log"]["entries"]:
        response = entry["response"]
        content = response.setdefault("content", {})

        fila = pendentes.get((entry["request"]["method"], entry["request"]["url"]))
        if not fila:
            continue

        status, body = fila.pop(0)
        if content.get("text") or not body:
            continue

        if response.get("status", -1) <= 0:
            response["status"] = status

        try:
            content["text"] = body.decode("utf-8")
            content.pop("encoding", None)
        except UnicodeDecodeError:
            content["text"] = base64.b64encode(body).decode("ascii")
            content["encoding"] = "base64"
        content["size"] = len(body)
        response["bodySize"] = len(body)
        injetados += 1

    if injetados:
        output_path.write_text(json.dumps(documento, ensure_ascii=False), encoding="utf-8")
    return injetados


def raise_network_buffer(context, page):
    try:
        session = context.new_cdp_session(page)
        session.send(
            "Network.enable",
            {
                "maxTotalBufferSize": CDP_TOTAL_BUFFER,
                "maxResourceBufferSize": CDP_RESOURCE_BUFFER,
            },
        )
    except Exception as e:
        print(f"  Aviso: não foi possível ampliar o buffer de rede desta página ({e})")


def classify_entries(entries, capturados=None):
    capturados = capturados or {}
    respostas_com_corpo = {
        (entry["request"]["method"], entry["request"]["url"], entry["response"].get("status"))
        for entry in entries
        if entry["response"].get("content", {}).get("text")
    }

    sem_corpo = []
    recuperaveis = []
    perdas = []

    for index, entry in enumerate(entries):
        response = entry["response"]
        if response.get("content", {}).get("text"):
            continue

        item = (index, entry["request"]["method"], response.get("status"), entry["request"]["url"])
        chave = (item[1], item[3], item[2])
        capturas = capturados.get((item[1], item[3]), [])
        if response.get("status") in BODYLESS_STATUS:
            sem_corpo.append(item)
        elif any(body for status, body in capturas if status == item[2]):
            perdas.append(item)
        elif chave in respostas_com_corpo:
            recuperaveis.append(item)
        elif response.get("bodySize", -1) <= 0 and response.get("_transferSize", -1) <= 0:
            sem_corpo.append(item)
        else:
            perdas.append(item)

    return sem_corpo, recuperaveis, perdas


def audit_har(output_path, stats, capturados=None):
    try:
        entries = json.loads(output_path.read_text(encoding="utf-8"))["log"]["entries"]
    except Exception as e:
        print(f"  Erro: não foi possível auditar o HAR ({e})")
        return

    sem_corpo, recuperaveis, perdas = classify_entries(entries, capturados)
    com_corpo = len(entries) - len(sem_corpo) - len(recuperaveis) - len(perdas)

    print()
    print("=" * 50)
    print("  Auditoria de completude")
    print("=" * 50)
    print(f"  entries                        : {len(entries)}")
    print(f"  com corpo gravado              : {com_corpo}")
    print(f"  sem corpo (esperado)           : {len(sem_corpo)}")
    print(f"  corpo disponível em outra entry: {len(recuperaveis)}")
    print(f"  PERDAS REAIS                   : {len(perdas)}")
    print(f"  requisições interceptadas      : {stats['interceptadas']}")
    print(f"  corpos injetados na gravação   : {stats['injetados']}")
    print(f"  ignoradas (condicional/stream) : {stats['ignoradas']}")
    print(f"  fallback (interceptação falhou): {stats['fallback']}")
    print("=" * 50)

    if not perdas:
        print("  HAR completo: nenhuma resposta com corpo foi perdida.")
        print()
        return

    print("  HAR INCOMPLETO — as respostas abaixo tinham corpo e ele não foi gravado:")
    for index, method, status, url in perdas:
        print(f"    entry {index:>4}  {method:<6}{status:>5}  {url}")
    print()
    print("  Regrave o fluxo. Se a mesma entry se repetir, o corpo foi descartado")
    print("  pelo navegador antes da gravação (streaming, navegação durante a resposta).")
    print()


def main():
    url = "http://127.0.0.1:8080/"
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"captura_{datetime.now().strftime('%Y%m%d_%H%M%S')}.har"

    print("=" * 50)
    print("  HAR Recorder")
    print("=" * 50)
    print(f"  URL inicial : {url}")
    print(f"  Output      : {output_path}")
    print("=" * 50)
    print()

    stats = {"interceptadas": 0, "ignoradas": 0, "fallback": 0, "injetados": 0}
    capturados = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-quic"])
        api_context = p.request.new_context()

        context = browser.new_context(
            record_har_path=str(output_path),
            record_har_mode="full",
            record_har_content="embed",
            service_workers="block",
        )

        context.route(INTERCEPT_URL_PATTERN, make_route_handler(api_context, capturados, stats))

        page = context.new_page()
        raise_network_buffer(context, page)
        context.on("page", lambda nova_page: raise_network_buffer(context, nova_page))

        browser_closed = False

        def on_disconnected():
            nonlocal browser_closed
            browser_closed = True

        browser.on("disconnected", on_disconnected)

        try:
            page.goto(url)
        except Exception as e:
            print(f"  Aviso: {e}")
            print("  (Verifique se o servidor em 127.0.0.1:8080 está rodando)")
            print()

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
        print("  Finalizando e gravando HAR...")

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

        try:
            api_context.dispose()
        except Exception:
            pass

    if output_path.exists():
        try:
            stats["injetados"] = inject_captured_bodies(output_path, capturados)
        except Exception as e:
            print(f"  Aviso: não foi possível injetar os corpos capturados ({e})")

        size_kb = output_path.stat().st_size / 1024
        print(f"  HAR gravado com sucesso!")
        print(f"  Arquivo : {output_path}")
        print(f"  Tamanho : {size_kb:.1f} KB")
        audit_har(output_path, stats, capturados)
    else:
        print("  Erro: HAR não foi gerado.")
        print()


if __name__ == "__main__":
    main()
