# HAR Recorder

Ferramenta simples para gravar a navegação em um site em um arquivo **HAR**
(HTTP Archive), incluindo o corpo das respostas (bodies), usando
[Playwright](https://playwright.dev/python/) para dirigir o navegador e
[mitmproxy](https://mitmproxy.org/) para capturar o tráfego real.

O script sobe um `mitmdump` local e abre um navegador Chromium apontado para
ele como proxy. Todo o tráfego passa pelo proxy sem ser reescrito ou
refeito — a resposta gravada é exatamente a que o servidor mandou, com
headers, cookies (`Set-Cookie` incluso) e corpo completo (mitmproxy já
descomprime `gzip`/`br` automaticamente). Ao final, o `.har` é escrito e o
script audita se alguma resposta com corpo esperado não foi gravada.

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

A URL inicial aberta no navegador está configurada em `record.py`, na função
`main()` — ajuste ali caso precise apontar para outro endereço.

```bash
uv run record.py
```

ou, usando o script configurado no `pyproject.toml`:

```bash
uv run record
```

O que acontece:

1. Um `mitmdump` local é iniciado numa porta livre, e um navegador Chromium é
   aberto (modo visível, não headless) apontado para esse proxy, já
   navegando para a URL configurada.
2. Navegue normalmente pelo site — todo o tráfego real passa pelo proxy e é
   capturado.
3. Para finalizar a gravação, feche o navegador **ou** pressione `Ctrl+C` no
   terminal.
4. O script salva o arquivo `.har` na pasta `output/`, com o nome no formato
   `captura_AAAAMMDD_HHMMSS.har`, encerra o `mitmdump`, e imprime um
   relatório de auditoria informando quantas entradas tiveram o corpo
   gravado e se houve alguma perda real de corpo de resposta.

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
  requisições HTTP/3 (QUIC) escapem do proxy.
- O navegador ignora avisos de certificado TLS (`ignore_https_errors`), já
  que o `mitmproxy` intercepta HTTPS com um certificado próprio — não é
  necessário instalar/confiar na CA do `mitmproxy` em lugar nenhum do
  sistema para gravar.
- Service workers são bloqueados durante a gravação para garantir que todo
  o tráfego passe pelo proxy.
- Diferente de uma versão anterior deste script (que interceptava cada
  requisição via Playwright e a refazia numa sessão HTTP paralela para
  capturar o corpo completo): esse mecanismo, embora capturasse o corpo,
  descartava o header `Set-Cookie` de toda resposta — o navegador nunca
  recebia esse header de volta ao ter a resposta "preenchida"
  (`route.fulfill`) manualmente, então nenhum `.har` gerado por ele tinha
  cookies de sessão gravados. É por isso que a captura passou a usar
  `mitmproxy` como proxy de rede de verdade, sem jamais recriar a resposta.
