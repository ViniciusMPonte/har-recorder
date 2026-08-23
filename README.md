# HAR Recorder

Ferramenta simples para gravar a navegação em um site em um arquivo **HAR**
(HTTP Archive), incluindo o corpo das respostas (bodies), usando
[Playwright](https://playwright.dev/python/).

O script abre um navegador Chromium, intercepta as requisições feitas pela
página, refaz cada requisição via uma sessão HTTP paralela para conseguir
capturar o corpo completo da resposta e injeta esse corpo no arquivo `.har`
gerado ao final. Ao terminar, ele audita o HAR gerado e informa se alguma
resposta com corpo esperado não foi gravada.

## Pré-requisitos

- Python 3.12 ou superior
- [uv](https://docs.astral.sh/uv/) (gerenciador de pacotes usado neste projeto)

## Instalação

1. Clone o repositório e entre na pasta do projeto:

   ```bash
   cd har-recorder
   ```

2. Instale as dependências com `uv`:

   ```bash
   uv sync
   ```

3. Instale o navegador Chromium usado pelo Playwright (necessário apenas na
   primeira vez):

   ```bash
   uv run playwright install chromium
   ```

## Como executar

O script espera que exista um servidor rodando em `http://127.0.0.1:8080/`
(essa é a URL inicial aberta no navegador — ajuste em `record.py` na função
`main()` caso precise apontar para outro endereço).

Com o servidor no ar, rode:

```bash
uv run record.py
```

ou, usando o script configurado no `pyproject.toml`:

```bash
uv run record
```

O que acontece:

1. Um navegador Chromium é aberto (modo visível, não headless) já navegando
   para a URL configurada.
2. Navegue normalmente pelo site — todas as requisições feitas durante a
   navegação são capturadas.
3. Para finalizar a gravação, feche o navegador **ou** pressione `Ctrl+C` no
   terminal.
4. O script salva o arquivo `.har` na pasta `output/`, com o nome no formato
   `captura_AAAAMMDD_HHMMSS.har`, e imprime um relatório de auditoria
   informando quantas entradas tiveram o corpo gravado, quantas foram
   ignoradas (ex.: streams, requisições condicionais) e se houve alguma perda
   real de corpo de resposta.

## Saída

Os arquivos gerados ficam em `output/`, por exemplo:

```
output/captura_20260817_210500.har
```

Esse arquivo pode ser aberto em ferramentas de análise de HAR (Chrome
DevTools, HAR Viewer, etc.) ou usado como entrada para reprodução de fluxos
(ex.: no projeto `har-flow-reproducer`).

## Observações

- O parâmetro `--disable-quic` é usado ao abrir o Chromium para evitar que
  requisições HTTP/3 (QUIC) escapem da interceptação.
- Requisições do tipo `media`, `websocket` e `eventsource`, assim como
  requisições condicionais (`If-None-Match` / `If-Modified-Since`), não são
  interceptadas e seguem seu fluxo normal (não têm o corpo re-capturado).
- Service workers são bloqueados durante a gravação para garantir que todas
  as requisições passem pela interceptação.
