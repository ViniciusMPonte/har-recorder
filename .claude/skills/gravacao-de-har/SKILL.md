---
name: gravacao-de-har
description: Grava a navegação num portal (login, valores pagos ou analítico) via `har-recorder` (mitmproxy + Playwright), identifica a entry inicial e final do fluxo pedido, reduz o `.har` com `reduzir_har.py` e monta o workspace na convenção que a skill `reproducao-de-har` (projeto `har-reproducer`) espera — deixando tudo pronto para essa skill começar direto no Passo 1. É a fase 0 do pipeline HAR → fluxo do robô (`har-recorder` → `har-reproducer`/`reproducao-de-har` → `workspace-para-fluxo-robot`/`oficina-de-fluxos`). Use SEMPRE que o usuário pedir para "gravar o fluxo de login/valores pagos/analítico do portal X", "gerar o fluxo tal para o convênio Y", "preciso de um HAR pra criar o fluxo do robô nesse portal", ou qualquer variação que já se refira ao objetivo final (fluxo pronto no robô) mas que precise começar pela captura.
---

# Gravação e redução de HAR — fase 0 do pipeline

Esta skill cobre só a primeira fase de um pipeline maior:

```
gravacao-de-har (esta skill)  →  reproducao-de-har (repo har-reproducer)  →  workspace-para-fluxo-robot / oficina-de-fluxos (repo http-robot-service)
      grava + reduz HAR              minimiza passos + extratores               gera o fluxo Groovy
```

O critério de pronto desta skill é objetivo: existe `<raiz>/<domínio>__<AAAAMMDD>_<HHMM>_<tipo>/<arquivo>.har`
(o `.har` já reduzido) na convenção que
`{har-reproducer}/.claude/skills/reproducao-de-har/references/workspace-setup.md`
descreve, pronto para uma sessão de `reproducao-de-har` começar direto no Passo 1
(`run`) sem precisar organizar nada. Esta skill **não roda `run`/`replay`/`optimize`** —
isso é responsabilidade da outra skill, noutra sessão.

## Passo 0 — perguntas iniciais (sempre, nesta ordem)

Não assuma nenhuma destas respostas; pergunte mesmo que o pedido do usuário pareça
implicar uma delas.

1. **URL inicial** — a que abre no navegador (geralmente a home/tela de login do
   portal).
2. **Tipo de fluxo**: login, valores pagos ou analítico. Se não for nenhum dos três,
   pare e pergunte como proceder — não force o encaixe. Os três padrões (o que cada
   um envolve em termos de requisições HTTP, e os riscos de sessão/efeito colateral
   de cada um) estão descritos em
   `{har-reproducer}/.claude/skills/reproducao-de-har/references/navigation-on-medical-portals.md`
   — leia esse arquivo antes de orientar o usuário sobre o roteiro de navegação do
   Passo 1, não repita de memória.
3. **Raiz dos workspaces do `har-reproducer`** — só perguntar se ainda não souber
   (nem nesta sessão, nem registrado em memória de sessões anteriores deste
   projeto). Depois de obtida, reaproveitar sempre, e salvar em memória (tipo
   `project`) para não perguntar de novo em sessões futuras.
4. **Domínio do portal** (para o nome da pasta) — normalmente dá pra extrair
   direto da URL inicial; só perguntar se houver ambiguidade real (múltiplos
   subdomínios/portas relevantes no mesmo fluxo).

## Passo 1 — gravar

- Rodar `uv run record.py <url>` (raiz deste repo, `har-recorder`) **em background**
  — abre um Chromium visível e o usuário navega nele.
- Antes de iniciar, alinhar com o usuário o roteiro mínimo esperado para o tipo de
  fluxo escolhido:
  - **login**: só entrar com as credenciais.
  - **valores pagos**: entrar + navegar até o resultado (consulta/download).
  - **analítico**: entrar + busca + abrir e baixar **um único item** da lista —
    não repetir a navegação para vários itens; a iteração sobre a lista inteira é
    responsabilidade do fluxo do robô (`TarefaIteravel`), não do HAR. Gravar mais
    de um item só infla o HAR sem ajudar o `har-reproducer` a minimizar nada.
- Esperar a task terminar (fechamento do navegador ou `Ctrl+C` do usuário) — a
  notificação de conclusão do harness avisa; não fazer polling ativo.
- Ler a auditoria de completude impressa ao final. Se aparecer "sem corpo
  (inesperado)", **investigar antes de assumir perda de captura**: abrir a entry,
  conferir `Content-Length` e headers da resposta. Um `200` com `Content-Length: 0`
  é legítimo (ex.: POST de login que só seta cookies, sem corpo) — `audit_har()`
  em `record.py` só reconhece `101/204/304` como bodyless por padrão, então esse
  caso aparece como falso positivo no relatório, não como perda real.

## Passo 2 — identificar entry inicial e final

- **Inicial**: geralmente a entry 0 (primeira requisição contra o domínio do
  portal — de onde sai o cookie/token de sessão anônima que o login vai
  reaproveitar), mas confirme pelo papel que ela exerce, não assuma o índice 0 de
  cabeça (mesma advertência de `navigation-on-medical-portals.md`).
- **Final** depende do tipo de fluxo:
  - **login**: a entry cujo conteúdo (JSON/HTML) comprova que autenticou de
    verdade — não só "200 OK", precisa ter algo no corpo que distinga sucesso de
    falha (nome do usuário, mensagem de boas-vindas, token). Em portais SPA
    (client-side rendered), esse texto pode nunca aparecer pronto num único HTML:
    o app monta a mensagem em duas partes (bundle JS estático com o texto fixo +
    endpoint JSON com o dado variável, ex. nome da organização). Nesse caso a
    entry final é a que entrega o **dado** (o JSON), não a renderização —
    documente isso ao usuário quando acontecer, é um caso legítimo, não uma
    limitação a contornar.
  - **valores pagos**: a entry que entrega o resultado (download do arquivo, ou
    o JSON/HTML com os valores).
  - **analítico**: a entry de download do único item navegado no Passo 1.
- Usar um script Python inline (`json.load` + iterar `log.entries`) para listar e
  inspecionar candidatos — nunca adivinhar por contagem de cliques feitos na
  gravação.
- Reportar ao usuário os índices encontrados e o motivo **antes** de reduzir —
  mesma disciplina de "não aceitar sucesso só pelo `status_code`" que
  `reproducao-de-har` usa depois.

## Passo 3 — reduzir

- Rodar `python3 reduzir_har.py <captura>.har --from <índice inicial> --to <índice
  final> -o <captura>_reduzido.har` (repo `har-recorder`, raiz deste projeto).
- Conferir que a última entry do arquivo resultante bate com o índice esperado
  (reabrir e inspecionar, não só confiar no `Mantidas N de M entradas` impresso).

## Passo 4 — montar o workspace pronto para o `reproducao-de-har`

- Extrair `AAAAMMDD` e `HHMM` do nome do arquivo de captura
  (`captura_AAAAMMDD_HHMMSS.har`) — data e hora da **captura**, não de hoje.
- Criar `<raiz>/<domínio>__<AAAAMMDD>_<HHMM>_<tipo>/`, onde `<tipo>` é o tipo
  de fluxo definido no Passo 0 (`login`/`valores_pagos`/`analitico`). O
  horário garante que duas capturas do mesmo domínio no mesmo dia nunca
  colidam — mesmo duas do mesmo tipo — sem precisar de sufixo improvisado
  na hora.
- Copiar (não mover) o `.har` reduzido para dentro dessa pasta — mantém o `.har`
  bruto em `output/` deste repo como histórico, intacto.
- **Não criar `output/` nem `git init` aqui** — isso é o Passo 0 de
  `reproducao-de-har`, roda na sessão que for consumir o workspace (naquele repo,
  naquela skill).
- Reportar ao usuário: caminho da pasta criada, e que o próximo passo é abrir uma
  sessão no repo `har-reproducer` com a skill `reproducao-de-har` apontando para
  esse workspace (Passo 1 dela em diante).

## Checklist final antes de encerrar

- [ ] HAR gravado, auditoria de completude sem pendência não explicada
- [ ] entry inicial e final identificadas e justificadas ao usuário
- [ ] `.har` reduzido conferido (última entry bate com o índice esperado)
- [ ] pasta de workspace criada na convenção `<raiz>/<domínio>__<AAAAMMDD>_<HHMM>_<tipo>/`
- [ ] usuário sabe que o próximo passo é `reproducao-de-har` (Passo 1) sobre essa
      pasta

## Casos de referência já encontrados

- **`entry` com `200` e corpo vazio não é sempre perda de captura**: portal
  `zeus.jmjsistemas.com.br`, fluxo de login — `POST /zeus/login` respondeu `200`
  com `Content-Length: 0`, sinalizado como "inesperado" pela auditoria de
  `record.py`. Investigação: a resposta só seta `Set-Cookie` (novo
  `JSESSIONID`/`CSRF-TOKEN`), sem corpo por design — a auditoria não trata `200`
  como bodyless por padrão, então isso aparece como falso positivo.
- **Texto de boas-vindas montado em duas requisições numa SPA**: mesmo portal —
  a frase "seja bem-vindo(a) ao JMJ ZEUS" está no bundle estático (`main.js`); o
  nome da organização vem de `GET /zeus/api/session`. A entry final do fluxo de
  login, nesse caso, é a `api/session` (índice 37 daquela captura), não uma
  entry de HTML.

## Referências externas (fora deste repositório)

| O quê | Onde | Por quê |
|---|---|---|
| Padrões de fluxo (login/valores pagos/analítico) e riscos de sessão | `{har-reproducer}/.claude/skills/reproducao-de-har/references/navigation-on-medical-portals.md` | Orienta o roteiro de navegação do Passo 1 e a identificação da entry final do Passo 2 |
| Convenção de pasta/nome do workspace | `{har-reproducer}/.claude/skills/reproducao-de-har/references/workspace-setup.md` | É a convenção que o Passo 4 desta skill precisa seguir exatamente |
| O que o `har-reproducer` faz a partir daqui | `{har-reproducer}/.claude/skills/reproducao-de-har/SKILL.md` | Não é preciso executar nada dela nesta skill, mas vale ler para saber o que a próxima sessão vai fazer com o workspace entregue |

Essas referências vivem noutro repositório (`har-reproducer`), então não são
invocáveis via `Skill` a partir daqui — leia os arquivos diretamente pelo caminho
do checkout quando precisar. Se o caminho do checkout ainda não foi informado
nesta sessão, pergunte antes de citar essas referências ao usuário.

## Checkpoint — aprendizado generalizável

Ao final de uma gravação (sucesso ou quando algo não se encaixou no processo
acima — um quarto tipo de fluxo, uma auditoria com pendência real, um portal que
não segue nenhum dos padrões descritos), pare e pergunte: **isso revelou algo que
valeria para qualquer gravação futura, não só para este portal?** Não é
obrigatório que sim. Se for, proponha o diff para este arquivo (ou para a seção
"Casos de referência") e espere aprovação antes de aplicar — nunca edite esta
skill sem mostrar o diff primeiro.
