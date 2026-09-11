---
name: orquestracao-fluxo-robot
description: Orquestra o pipeline inteiro do pedido do usuário até o fluxo do robô testado — grava o HAR (gravacao-de-har), minimiza e resolve extratores (reproducao-de-har, repo har-reproducer), traduz para a DSL do robô e roda os testes (workspace-para-fluxo-robot + oficina-de-fluxos, repo http-robot-service) — com UMA ÚNICA fase de interação com o usuário (a gravação: URL, tipo de fluxo, raiz do workspace, e a navegação em si). Tudo depois disso roda sem pausar, seguindo um contrato de autonomia explícito que resolve por política padrão cada ponto que as skills de origem normalmente perguntariam, preservando só os hard stops de segurança genuínos (divergência não resolvida, endpoint fora do HAR, credencial expirada, etc.). Use SEMPRE que o usuário pedir o fluxo fim-a-fim de forma autônoma — "gera esse fluxo pro convênio X do início ao fim", "automatiza esse portal sozinho depois que eu gravar", "quero só gravar e o resto ser automático" — e não apenas uma das fases isoladas (para isso, use `gravacao-de-har` sozinha).
---

# Orquestração ponta a ponta — HAR → fluxo do robô testado

Esta skill não substitui nenhuma das quatro skills que ela orquestra — só define **a
ordem** em que rodam e **o contrato de autonomia** que faz a cadeia inteira andar
sem pausar depois da gravação. Tudo que já está resolvido nelas não é repetido
aqui.

```
gravacao-de-har          reproducao-de-har         workspace-para-fluxo-robot  +  oficina-de-fluxos
(repo har-recorder)   →  (repo har-reproducer)  →  (repo har-reproducer, ponte)    (repo http-robot-service)
   grava + reduz HAR       minimiza + extratores        traduz workspace → DSL Groovy + testes
   ÚNICA FASE INTERATIVA        autônoma                          autônoma
```

## O contrato de autonomia

Esta tabela é o núcleo desta skill. Cada linha é um ponto em que uma das quatro
skills de origem normalmente pergunta ao usuário — a política aqui substitui a
pergunta por uma decisão padrão, com a razão pela qual isso é seguro **neste
pipeline especificamente** (login/valores pagos/analítico, sempre leitura/consulta,
nunca escrita/transmissão). As linhas marcadas **hard stop** continuam parando a
execução e devolvendo a decisão ao usuário — não foram removidas, só a maioria dos
pontos foi.

| # | Ponto de decisão | Origem | Política nesta orquestração |
|---|---|---|---|
| 1 | Primeira execução de `run --mode main` | `guardrails.md` §2 | **Autônomo.** Pular a pergunta — os três tipos de fluxo desta pipeline são sempre leitura/consulta, a exceção que a própria regra já prevê. |
| 2 | Rodar `optimize` | `guardrails.md` §6 | **Autônomo** (decisão explícita do usuário nesta sessão, sobrescrevendo a regra padrão que não tem exceção de leitura). Mantém `--max-requests` no padrão da ferramenta e para se divergir (linha 5). |
| 3 | Ritmo entre requisições reais | `guardrails.md` §3 | **Autônomo, sempre no modo mais conservador.** Tratar todo alvo como produção real (nunca sandbox) — pacing mais espaçado da faixa sugerida quanto maior o volume (`optimize`, fluxo analítico) e mais perto do limite inferior em execuções pontuais de poucos passos. Latência crescente entre respostas = sinal de estresse no portal → espaçar mais, nunca manter o ritmo. |
| 4 | Aumentar `--max-requests` do `optimize` | `guardrails.md` §3 | **Nunca.** Se o padrão não bastar, é sinal de que o fluxo não é trivial de minimizar — hard stop (linha 5), não aumentar sozinho. |
| 5 | Divergência que persiste após uma tentativa de correção | `reproducao-de-har` Passo 3 / `diagnostics.md` | **Hard stop.** Causa real (bug, mudança de portal, sessão expirada) exige julgamento humano — reportar e parar, nunca insistir sozinho numa segunda tentativa. |
| 6 | `run`/`replay` falhando por erro de conexão (não divergência de conteúdo) | `guardrails.md` §3 | **Hard stop.** Não repetir sozinho. |
| 7 | Passo necessário que não corresponde a nenhuma requisição do HAR capturado / explorar endpoint novo | `guardrails.md` §4, `captura-navegacao.md` | **Hard stop, sempre.** Nunca inventar uma requisição fora do que foi capturado na gravação — se a tradução pro robô parecer exigir isso, parar e reportar em vez de "completar" por conta própria. |
| 8 | Sinal de efeito colateral não-idempotente em algum passo (o usuário comenta algo do tipo "isso gerou/alterou um registro" durante a navegação) | `guardrails.md` §2 | **Hard stop.** Foge do escopo leitura/consulta que justifica toda a autonomia das fases seguintes — se acontecer, a orquestração para ali e devolve a decisão ao usuário antes de rodar qualquer `run`/`replay`/`optimize`. |
| 9 | `--required-steps-file` do `optimize` (tela inicial + login) | `navigation-on-medical-portals.md` | **Autônomo, sempre declarado.** Os três tipos de fluxo desta pipeline sempre incluem login na captura (valores pagos/analítico pressupõem sessão autenticada, então o login está no HAR reduzido) — identificar os dois índices por inspeção do workspace (papel da requisição, não posição por convenção) e declarar antes da primeira chamada, sem esperar o falso positivo acontecer. |
| 10 | Registrar site/operadora novo em `Sites.json` | `oficina-de-fluxos` passo 9 | **Autônomo, mecânico.** O convênio/portal já veio do pedido inicial do usuário (Fase 1) — não é ambiguidade a resolver, é preencher o registro seguindo o padrão do arquivo. |
| 11 | Plataforma genérica (Portal Solus/Fácil/etc.) vs. fluxo próprio | `oficina-de-fluxos` passo 2 | **Autônomo**, decidido por inspeção de `Sites.json`/pacotes `convenio/{plataforma}/` existentes — critério objetivo já documentado ali. |
| 12 | Job (`DownloadArquivosSiteJob` vs. `ProcessadorSiteJob`) | `oficina-de-fluxos` passo 3 | **Autônomo** — critério objetivo (baixa arquivo → Download; senão → Processador). |
| 13 | Nova arquitetura de pagamentos obrigatória | `oficina-de-fluxos` / `nova-arquitetura-pagamentos.md` | **Autônomo, sempre aplicada** para os tipos valores pagos/analítico — não é escolha, é regra do projeto. |
| 14 | `bloqueiaExecucoesSimultaneas` vs. `...PorCredencial` | `features-avancadas.md` §4 | **Autônomo** — o workspace só tem uma sessão/credencial gravada; usar a variante por credencial por padrão (critério técnico, não preferência). |
| 15 | `ignoreSSLIssues()` | `padroes-e-boas-praticas.md` | **Autônomo, só se comprovadamente necessário** — incluir apenas se `run`/`replay` contra o portal real exigiu ignorar erro de certificado; nunca copiar de outro Helper "por garantia". |
| 16 | Gravar o replay spec do robô contra o portal real (`FixtureMode.RECORD`) | `workspace-para-fluxo-robot` (guardrail próprio) | **Autônomo, mas a credencial em texto puro precisa ter sido pedida explicitamente — a navegação da Fase 1 não entrega isso sozinha.** A primeira condição do guardrail (fluxo é leitura/consulta) sempre vale nesta pipeline. A segunda ("credenciais fornecidas explicitamente pelo usuário para esse fim") **não** se resolve só porque a Fase 3 reusa "a mesma sessão da Fase 1": na gravação ao vivo o usuário digita a senha direto no navegador, e o agente nunca a vê em texto puro — só enxerga o HAR, que pode conter apenas um hash calculado no cliente (ex.: MD5 antes do POST). Por isso a linha 21 abaixo pede usuário/senha em texto puro já na Fase 1, para a Fase 3 não travar no meio perguntando o que já podia ter sido coletado no início. |
| 17 | Credencial hardcoded de um spec de replay **expirada** (achado ao tentar gravar o cache) | `oficina-de-fluxos` (nota de gravação) | **Hard stop.** Explícito na skill de origem: "não decida sozinho, pergunte ao dev". Nesta pipeline isso normalmente significa: a sessão capturada na Fase 1 expirou antes de a Fase 3 conseguir regravar — parar e reportar; pode exigir gravar um HAR novo. |
| 18 | LLM fallback do `har-reproducer` (`config.json`) para resolver token | `guardrails.md` §5 | **Nunca habilitar/alterar por conta própria.** Manter a configuração como já está no workspace; um extrator que só resolveria via LLM desligado vira uma lacuna sinalizada no relatório final, não um motivo para ligar o fallback sozinho. |
| 19 | Push / abrir PR no `http-robot-service` | Regra operacional desta sessão (não da skill) | **Hard stop, sempre.** A entrega para em commit local numa branch `dev-feature-{slug}`; push/PR só acontece se o usuário pedir explicitamente numa mensagem separada, depois de revisar. |
| 20 | Exibir conteúdo sensível capturado (tokens, cookies, senha) | `guardrails.md` §5 | **Nunca em texto solto.** O relatório final resume o que foi feito, não reproduz o corpo de respostas capturadas. |
| 21 | Coletar usuário/senha em texto puro para a gravação de cache da Fase 3 (linha 16) | Aprendizado desta própria orquestração (achado em execução real) | **Perguntar já na Fase 1**, como pergunta extra da janela interativa — junto com URL/tipo de fluxo/raiz do workspace do Passo 0 de `gravacao-de-har`, não como pergunta separada depois. Vale para os três tipos de fluxo (login/valores pagos/analítico pressupõem login). Tratar a resposta como dado efêmero desta sessão (mesma disciplina da linha 20: nunca em texto solto no relatório final; só usada dentro do código do spec de teste, que é o padrão hardcoded do próprio `oficina-de-fluxos` para specs de replay). Se o usuário preferir não fornecer agora, seguir sem a credencial e sinalizar no relatório final da Fase 4 que a gravação do cache ficou pendente (mesma saída que `oficina-de-fluxos` já prevê para "credenciais indisponíveis") — não é hard stop, só lacuna documentada. |

## Processo

### Fase 1 — gravação (a única fase interativa)

Invocar a skill `gravacao-de-har` (mesmo repositório) via `Skill`. As perguntas do
Passo 0 dela (URL, tipo de fluxo, raiz do workspace, domínio) **são** a janela de
interação que esta orquestração preserva — não pular nem pré-responder nenhuma.
Os Passos 1–4 dela (gravar, identificar entry inicial/final, reduzir, montar
workspace) já são não-interativos por design daquela skill — seguir exatamente
como documentado ali, sem pausar entre eles.

**Além das perguntas de `gravacao-de-har`, pedir também usuário/senha em texto
puro do login usado nesta captura** (linha 21 do contrato) — a navegação ao vivo
não entrega isso ao agente (o usuário digita direto no navegador), e a Fase 3
precisa da credencial real para gravar o cache do replay spec (linha 16). Pedir
isso já aqui evita descobrir a falta dela só no meio da Fase 3, quando o
workspace já está pronto e tudo mais já rodou sem pausar. Se o usuário preferir
não fornecer agora, seguir sem — vira lacuna sinalizada no relatório da Fase 4,
não um bloqueio da Fase 1/2.

Ignorar o "Checkpoint — aprendizado generalizável" do fim de `gravacao-de-har`
(é uma pergunta sobre atualizar a skill em si, não faz parte da entrega) — se
algo digno de nota aparecer, registrar no relatório final (Fase 4) em vez de
perguntar ali.

**Se em algum momento da navegação o usuário sinalizar um efeito colateral não-
idempotente** (linha 8 do contrato): parar aqui, antes de abrir a Fase 2 — não é
mais um fluxo de leitura/consulta puro, e o resto desta orquestração pressupõe que
é.

Ao final da Fase 1: confirmar que `<raiz>/<domínio>__<AAAAMMDD>/<arquivo>.har`
existe e seguir direto para a Fase 2, sem esperar aprovação.

### Fase 2 — reprodução mínima (`reproducao-de-har`, repo `har-reproducer`)

Localizar o checkout de `har-reproducer` (buscar pelo marcador
`.claude/skills/reproducao-de-har/SKILL.md`; se a sessão já sabe o caminho de uma
interação anterior, reaproveitar). **Esta é a única exceção de setup que pode
exigir uma pergunta** — só se a busca automática não encontrar nada ou encontrar
mais de um candidato ambíguo.

Ler `SKILL.md` e os `references/` daquele diretório normalmente (ela já orienta
isso) e seguir os Passos 0–5 dela como estão escritos, com as substituições do
contrato de autonomia:

- **Passo 0** (organizar workspace): já feito pela Fase 1 — só confirmar que
  `output/` ainda não existe ali e inicializar o repositório git dentro dele,
  exatamente como `workspace-setup.md` descreve.
- **Passo 1** (`run --mode main`): rodar direto (linha 1 do contrato). Rodar
  `extractor list` antes de seguir.
- **Passo 2** (`replay --mode all`): rodar direto.
- **Passo 3** (diagnosticar): seguir a disciplina normal — nunca aceitar sucesso
  só por `status_code`, corrigir extrator só via comando `extractor` (nunca
  editar `.py`/`.meta.json` à mão). Se a divergência não resolver após uma
  tentativa: **hard stop** (linha 5).
- **Passo 4** (`optimize`): identificar por inspeção do workspace (não por
  posição assumida) o índice da requisição da tela inicial e o do login, gravar
  num `.txt` e declarar `--required-steps-file` **antes da primeira chamada**
  (linha 9). Rodar sem pausar (linha 2), `--max-requests` no padrão (linha 4),
  pacing conservador (linha 3). Conferir no `.txt` de saída que os dois índices
  sobreviveram.
- **Passo 5** (validar a frio): `replay --mode list --steps-file` num contexto
  que não reaproveite cache/jar do `optimize`. Este é o critério objetivo de
  "workspace finalizado" que a Fase 3 exige como pré-condição.

### Fase 3 — tradução para o robô (`workspace-para-fluxo-robot` + `oficina-de-fluxos`)

Confirmar a pré-condição (Passo 5 da Fase 2 concluído). Localizar o checkout de
`http-robot-service` (mesma lógica de auto-descoberta da Fase 2, marcador
`.claude/skills/oficina-de-fluxos/SKILL.md`). Ler
`{http-robot-service}/.claude/skills/oficina-de-fluxos/SKILL.md` diretamente pelo
caminho do arquivo (não é invocável via `Skill` — vive noutro repositório).

Seguir o Processo 1–6 de `workspace-para-fluxo-robot`:

1. Montar o mapa de captura a partir do workspace (não do navegador).
2. Rodar a triagem normal de `oficina-de-fluxos` sobre o convênio/portal — aqui
   entram as linhas 10–14 do contrato, todas autônomas por critério objetivo.
3. Traduzir cada elemento do workspace para a sintaxe da DSL
   (`references/mapa-de-traducao.md`) — sinalizar lacunas explicitamente (linha
   18 do contrato cobre o caso de token sem extrator determinístico), nunca
   resolver por adivinhação.
4. Escrever a DSL compilada + Helper (`dsl.md` + `dsl-compilada-sintaxe.md` +
   `padroes-e-boas-praticas.md` de `oficina-de-fluxos`) — linha 15 do contrato
   para `ignoreSSLIssues()`. Se algum passo necessário não tiver requisição
   correspondente no workspace: **hard stop** (linha 7).
5. Gerar o replay spec e gravar o cache contra o portal real — autorizado sem
   perguntar (linha 16); se uma credencial usada no spec aparecer expirada:
   **hard stop** (linha 17).
6. Rodar os testes indicados (`HeadlessBuilderTest` filtrado pelo fluxo,
   `SitesSpec` se `Sites.json` mudou, `ExecucaoScripts{Convenio}Spec`) — sempre
   com `--tests`, nunca a suíte inteira.

Checklist final: o de `padroes-e-boas-praticas.md` (canônico) + os itens de
origem específicos listados no fim de `workspace-para-fluxo-robot/references/processo.md`.

### Fase 4 — entrega e relatório final

- **Branch: a decisão depende de existir ticket ou não.**
  - **Existe ticket** (o usuário mencionou um `ZG-XXXX` nesta sessão, ou o
    repositório já está numa branch `dev-{hotfix|feature}-ZG-\d+`): usar
    exatamente essa branch, sem exceção. A orquestração **nunca** cria,
    procura ou troca de branch por conta própria nesse caso — não é decisão
    dela, é decisão de ticket/processo normal de `oficina-de-fluxos`. Os
    commits deste fluxo entram ali, junto com o resto do trabalho do ticket.
  - **Não existe ticket** (caminho autônomo padrão desta pipeline, sem Jira):
    aplicar "uma branch por convênio, não por fluxo" — mas só reaproveitando
    uma branch que **já siga o padrão sem-ticket desta própria pipeline**
    (`dev-feature-{convênio}`, sem token `ZG-\d+` no nome). Nunca reaproveitar
    uma branch qualquer só porque ela toca o mesmo convênio — pode ser
    trabalho de outra pessoa, de outro ticket, sem relação com esta pipeline.
    - **Se existir** uma branch `dev-feature-{convênio}*` local, sem ticket
      no nome, ainda não mergeada: `git checkout` nela e commitar o fluxo
      novo ali (mais um commit, mesma branch) — nunca criar uma branch nova,
      nem irmã, nem a partir dela, só porque o tipo de fluxo mudou.
    - **Se não existir**: criar `dev-feature-{slug}` a partir da branch
      principal atualizada, com `{slug}` sendo só o **convênio**
      (ex.: `dev-feature-hapvida`, não `dev-feature-hapvida-valores-pagos`)
      — o tipo de fluxo fica na mensagem de commit, não no nome da branch,
      já que a branch pode acumular vários tipos de fluxo do mesmo convênio
      antes de mergear. Ausência de ticket Jira nesta pipeline autônoma
      continua sendo o motivo do desvio da convenção `dev-feature-{TICKET}`
      observada em `oficina-de-fluxos`.
- Commitar seguindo o padrão observado (`tipo: descrição em português`). **Não**
  gerar o commit de confirmação de breaking change/indisponibilidade — ele só é
  exigido antes de ir para a branch principal, e esta entrega para antes disso;
  sinalizar isso no relatório.
- **Não** fazer push, **não** abrir PR (linha 19 do contrato) — mesmo que tudo
  tenha passado.
- Emitir o relatório final, sempre com esta estrutura (compensa não ter havido
  nenhuma outra pergunta pelo caminho):
  1. Fluxo gerado: tipo, convênio/portal, URL inicial.
  2. Workspace `har-reproducer`: caminho, nº de passos minimizados, extratores
     criados/corrigidos e o que cada um resolve.
  3. Decisões autônomas que realmente aconteceram neste fluxo (que linhas do
     contrato foram acionadas, ex.: "`optimize` rodou N vezes sem pausar, M
     requisições reais no total").
  4. Lacunas sinalizadas (extrator sem correspondência determinística,
     `success_criteria` sem validador dedicado), se houver.
  5. Fluxo Groovy: arquivo(s), Helper, categoria (`LOGIN`/`PAGAMENTOS`), site(s)
     em `Sites.json`.
  6. Testes rodados e resultado, com o comando exato usado.
  7. Branch usada (de ticket reaproveitada, de convênio nova, ou de convênio
     reaproveitada) e commit(s) criados (hash, mensagem) — sem push.
  8. Próximo passo sugerido ao usuário (revisar diff, decidir push/PR).
  9. Se algum hard stop interrompeu a execução antes do fim: reportar até onde
     chegou, marcado claramente como incompleto — nunca apresentar como
     "concluído" um resultado parcial.

## Hard stops — lista compacta

A orquestração para e devolve a decisão ao usuário quando: (5) uma divergência
persiste após correção; (6) `run`/`replay` falha por erro de conexão; (7) um
passo necessário não tem requisição correspondente no HAR capturado; (8) surge
sinal de efeito colateral não-idempotente durante a gravação; (17) uma credencial
usada no spec de replay está expirada; (19, sempre) ao chegar em push/PR no
`http-robot-service`. Fora dessas linhas do contrato, a execução não pausa.

## Referências externas (fora deste repositório)

| O quê | Onde |
|---|---|
| Processo completo de reprodução mínima | `{har-reproducer}/.claude/skills/reproducao-de-har/SKILL.md` + `references/` |
| Padrões de fluxo em portais médicos | `{har-reproducer}/.claude/skills/reproducao-de-har/references/navigation-on-medical-portals.md` |
| Tradução workspace → fluxo do robô | `{har-reproducer}/.claude/skills/workspace-para-fluxo-robot/SKILL.md` + `references/` |
| Geração de fluxo Groovy, triagem, DSL, testes | `{http-robot-service}/.claude/skills/oficina-de-fluxos/SKILL.md` + `references/` |

Nenhuma delas é invocável via `Skill` a partir daqui (vivem em repositórios
diferentes) — ler os arquivos diretamente pelo caminho do checkout.

## Checkpoint — aprendizado generalizável

Ao final de qualquer execução desta orquestração — completa ou interrompida num
hard stop — parar e perguntar: **essa execução revelou um ponto de decisão que
deveria entrar no contrato de autonomia (uma linha nova, ou uma política que se
mostrou errada), ou um hard stop que na prática nunca deveria ter sido
autônomo?** Se sim, propor o diff para este arquivo e esperar aprovação antes de
aplicar — nunca editar esta skill sem mostrar o diff primeiro.
