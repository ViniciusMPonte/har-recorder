import sys
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright


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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        context = browser.new_context(
            record_har_path=str(output_path),
            record_har_mode="full",
            record_har_content="embed",
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

        try:
            context.close()
        except Exception:
            pass

        try:
            browser.close()
        except Exception:
            pass

    if output_path.exists():
        size_kb = output_path.stat().st_size / 1024
        print(f"  HAR gravado com sucesso!")
        print(f"  Arquivo : {output_path}")
        print(f"  Tamanho : {size_kb:.1f} KB")
    else:
        print("  Erro: HAR não foi gerado.")

    print()


if __name__ == "__main__":
    main()