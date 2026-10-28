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

A URL inicial aberta no navegador é passada como argumento:

```bash
uv run record.py https://exemplo.com.br/
```

ou, usando o script configurado no `pyproject.toml`:

```bash
uv run record https://exemplo.com.br/
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

## Extensão do Chrome (alternativa sem proxy)

`extensao-chrome/` grava o mesmo `.har` (mesmo formato do `har_addon.py`)
direto no seu Chrome, sem mitmproxy nem Playwright. Usa o `chrome.debugger`
(DevTools Protocol) e segura cada resposta até ler o corpo, como o proxy faz.
Não sofre do problema de HTTP/2 que pede `--sem-http2`.

Instalar (uma vez): `chrome://extensions` → ative **Modo do desenvolvedor** →
**Carregar sem compactação** → escolha a pasta `extensao-chrome/`.

Gravar:

1. Abra uma aba (de preferência numa janela anônima ou num perfil limpo —
   a extensão usa os cookies que o navegador já tem; para isso, permita a
   extensão no modo anônimo em "Detalhes").
2. Clique no ícone da extensão: aparece `REC` e a barra amarela
   "HAR Recorder começou a depurar este navegador".
3. Navegue até a URL inicial e faça o fluxo. Popups e iframes de outra
   origem abertos pela aba também são gravados.
4. Clique no ícone de novo (ou feche a aba, ou "Cancelar" na barra amarela).
   O arquivo vai para `Downloads/har-recorder/captura_AAAAMMDD_HHMMSS.har`.
   A auditoria de corpo aparece no tooltip do ícone (`!` = tem resposta sem
   corpo; a lista sai no console do service worker).

Diferenças para o `record.py`: cache e service worker ficam desligados como
no contexto do Playwright, mas os cookies e o perfil são os do navegador;
corpo de redirect (3xx) não é gravado; a primeira resposta de um popup pode
vir sem corpo se carregar antes do attach.

Teste: `uv run python extensao-chrome/teste_extensao.py`.
