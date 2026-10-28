// Grava o tráfego da aba pelo Chrome DevTools Protocol (chrome.debugger) e salva um .har
// no mesmo formato do har_addon.py (mitmproxy), para servir de entrada ao har-reproducer.

const BODYLESS_STATUS = new Set([101, 204, 304]);
const NETWORK_ENABLE = { maxTotalBufferSize: 512 * 1024 * 1024, maxResourceBufferSize: 128 * 1024 * 1024 };

// shortcut: estado só em memória; a sessão de debugger mantém o service worker vivo (Chrome 118+),
// mas se ele morrer a gravação se perde — persistir em chrome.storage se isso acontecer na prática.
let rec = null;

chrome.action.onClicked.addListener((tab) => (rec ? stop() : start(tab.id)));

// Popups e target=_blank abertos pela aba gravada também são gravados (como no contexto do Playwright).
// shortcut: o attach acontece depois de a aba nascer; se a 1ª request do popup escapar, trocar por um fluxo que pause a aba.
chrome.tabs.onCreated.addListener((tab) => {
  if (rec && rec.tabs.has(tab.openerTabId)) attach(rec, tab.id).catch((e) => console.warn("attach popup", e.message));
});

chrome.debugger.onDetach.addListener((source) => {
  if (!rec) return;
  rec.tabs.delete(source.tabId);
  if (rec.tabs.size === 0) stop(); // aba fechada ou "Cancelar" na barra amarela do Chrome
});

async function start(tabId) {
  rec = { tabs: new Set(), flows: new Map(), entries: [], inflight: new Set(), startedAt: new Date() };
  try {
    await attach(rec, tabId);
  } catch (e) {
    rec = null;
    chrome.action.setTitle({ title: `HAR Recorder: não deu para gravar esta aba (${e.message})` });
    return;
  }
  chrome.action.setBadgeBackgroundColor({ color: "#c00" });
  chrome.action.setBadgeText({ text: "REC" });
  chrome.action.setTitle({ title: "HAR Recorder: gravando. Clique para parar e salvar o .har" });
}

async function attach(r, tabId) {
  await chrome.debugger.attach({ tabId }, "1.3");
  r.tabs.add(tabId);
  await setupTarget({ tabId });
}

// Equivalente ao new_context do record.py: sem cache e sem service worker, para gravar a resposta real do servidor.
// Auto-attach pega iframes de outra origem (processo separado) e workers, que o proxy também via.
async function setupTarget(target) {
  await send(target, "Network.enable", NETWORK_ENABLE);
  await send(target, "Network.setCacheDisabled", { cacheDisabled: true });
  await send(target, "Network.setBypassServiceWorker", { bypass: true });
  // Segura cada resposta até ler o corpo, como o proxy: o Network.getResponseBody perde o corpo quando a página navega logo depois.
  await send(target, "Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Response" }] });
  await send(target, "Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: true, flatten: true });
}

// Nem todo target aceita todo comando (ex.: worker sem cache); o erro não pode travar o runIfWaitingForDebugger.
function send(target, method, params) {
  return chrome.debugger.sendCommand(target, method, params).catch((e) => console.warn(method, e.message));
}

function track(r, promise) {
  r.inflight.add(promise);
  promise.finally(() => r.inflight.delete(promise));
}

// Um requestId cobre a cadeia de redirects inteira: cada salto vira um "hop" e vira uma entry no fim.
// Os *ExtraInfo (headers reais, com Cookie e Set-Cookie) chegam antes ou depois do evento principal, então
// são pareados com os hops pela ordem de chegada.
function flowOf(r, key) {
  let flow = r.flows.get(key);
  if (!flow) r.flows.set(key, (flow = { hops: [], requestExtra: [], responseExtra: [] }));
  return flow;
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  const r = rec;
  const target = source.sessionId ? { tabId: source.tabId, sessionId: source.sessionId } : { tabId: source.tabId };
  if (!r) {
    if (method === "Fetch.requestPaused") send(target, "Fetch.continueRequest", { requestId: params.requestId });
    return;
  }
  r.lastEventAt = Date.now();
  // Sem sessionId na chave: a navegação de um iframe de outra origem começa na sessão da página e termina na do iframe.
  const key = `${source.tabId}|${params.requestId}`;

  switch (method) {
    case "Fetch.requestPaused": {
      const flow = params.networkId && flowOf(r, `${source.tabId}|${params.networkId}`);
      const redirect = params.responseStatusCode >= 300 && params.responseStatusCode < 400;
      const read = flow && !redirect
        ? chrome.debugger.sendCommand(target, "Fetch.getResponseBody", { requestId: params.requestId })
          .then((body) => { flow.body = body; })
          .catch((e) => console.warn("Fetch.getResponseBody", params.request.url, e.message))
        : Promise.resolve();
      track(r, read.then(() => send(target, "Fetch.continueRequest", { requestId: params.requestId })));
      break;
    }
    case "Target.attachedToTarget": {
      const child = { tabId: source.tabId, sessionId: params.sessionId };
      setupTarget(child).then(() => send(child, "Runtime.runIfWaitingForDebugger"));
      break;
    }
    case "Network.requestWillBeSent": {
      const flow = flowOf(r, key);
      if (params.redirectResponse && flow.hops.length) flow.hops.at(-1).response = params.redirectResponse;
      const hop = {
        startedDateTime: new Date(params.wallTime * 1000).toISOString(),
        request: params.request,
        postData: postDataText(params.request),
      };
      flow.hops.push(hop);
      if (params.request.hasPostData && hop.postData === undefined) {
        track(r, chrome.debugger.sendCommand(target, "Network.getRequestPostData", { requestId: params.requestId })
          .then((res) => { hop.postData = res.base64Encoded ? decodeUtf8(base64Bytes(res.postData)) : res.postData; })
          .catch(() => {}));
      }
      break;
    }
    case "Network.requestWillBeSentExtraInfo":
      flowOf(r, key).requestExtra.push(params);
      break;
    case "Network.responseReceivedExtraInfo":
      flowOf(r, key).responseExtra.push(params);
      break;
    case "Network.responseReceived": {
      const flow = r.flows.get(key);
      if (flow?.hops.length) flow.hops.at(-1).response = params.response;
      break;
    }
    case "Network.loadingFinished": {
      // Fallback para o que o Fetch não segurou (ex.: 1ª resposta de um popup, antes do attach).
      const flow = r.flows.get(key);
      const read = flow && !flow.body
        ? chrome.debugger.sendCommand(target, "Network.getResponseBody", { requestId: params.requestId })
          .then((body) => { flow.body = body; })
          .catch(() => {})
        : Promise.resolve();
      track(r, read.then(() => finish(r, key)));
      break;
    }
    case "Network.loadingFailed":
      finish(r, key);
      break;
  }
});

function finish(r, key) {
  const flow = r.flows.get(key);
  if (!flow) return;
  r.flows.delete(key);
  flow.hops.forEach((hop, i) => {
    // Como o har_addon.py: só entra quem teve resposta; data:/blob: nunca passariam pelo proxy.
    if (!hop.response || !/^https?:/.test(hop.request.url)) return;
    const last = i === flow.hops.length - 1;
    r.entries.push(buildEntry(hop, flow.requestExtra[i], flow.responseExtra[i], last ? flow.body : null));
  });
}

function buildEntry(hop, requestExtra, responseExtra, body) {
  const requestHeaders = headerList(requestExtra?.headers ?? hop.request.headers);
  const responseHeaders = headerList(responseExtra?.headers ?? hop.response.headers);

  const request = { method: hop.request.method, url: hop.request.url, headers: requestHeaders, cookies: requestCookies(requestHeaders) };
  if (hop.postData) request.postData = { text: hop.postData };

  const response = {
    status: responseExtra?.statusCode ?? hop.response.status,
    headers: responseHeaders,
    cookies: responseCookies(responseHeaders),
    content: buildContent(body, headerValue(responseHeaders, "content-type") ?? ""),
  };
  const location = headerValue(responseHeaders, "location");
  if (location !== undefined) response.redirectUrl = location;

  return { startedDateTime: hop.startedDateTime, request, response };
}

// O CDP junta valores repetidos (ex.: vários Set-Cookie) com "\n" e, em HTTP/2, inclui pseudo-headers (":authority"),
// que o mitmproxy não põe na lista de headers.
function headerList(headers) {
  return Object.entries(headers ?? {})
    .filter(([name]) => !name.startsWith(":"))
    .flatMap(([name, value]) => String(value).split("\n").map((v) => ({ name, value: v })));
}

function headerValue(headers, name) {
  return headers.find((h) => h.name.toLowerCase() === name)?.value;
}

function nameValue(pair) {
  const at = pair.indexOf("=");
  return at < 0 ? { name: pair.trim(), value: "" } : { name: pair.slice(0, at).trim(), value: pair.slice(at + 1).trim() };
}

function requestCookies(headers) {
  return headers
    .filter((h) => h.name.toLowerCase() === "cookie")
    .flatMap((h) => h.value.split(";"))
    .filter((pair) => pair.trim())
    .map(nameValue);
}

function responseCookies(headers) {
  return headers.filter((h) => h.name.toLowerCase() === "set-cookie").map((h) => nameValue(h.value.split(";")[0]));
}

function postDataText(request) {
  if (request.postDataEntries?.length) {
    return decodeUtf8(concatBytes(request.postDataEntries.map((e) => base64Bytes(e.bytes ?? ""))));
  }
  return request.postData;
}

// Mesma regra do har_addon.py: texto se for UTF-8 válido, senão base64.
function buildContent(body, mimeType) {
  if (!body?.body) return { text: "", mimeType, size: 0 };
  if (!body.base64Encoded) return { text: body.body, mimeType, size: new TextEncoder().encode(body.body).length };
  const bytes = base64Bytes(body.body);
  try {
    return { text: new TextDecoder("utf-8", { fatal: true }).decode(bytes), mimeType, size: bytes.length };
  } catch {
    return { text: body.body, mimeType, encoding: "base64", size: bytes.length };
  }
}

function base64Bytes(text) {
  return Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
}

function bytesToBase64(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

function concatBytes(parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const p of parts) { out.set(p, offset); offset += p.length; }
  return out;
}

function decodeUtf8(bytes) {
  return new TextDecoder("utf-8").decode(bytes); // substitui bytes inválidos, como errors="replace"
}

function timestamp(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

// Mesma auditoria do record.py. Redirect fica de fora porque o CDP não entrega corpo de 3xx.
function audit(entries) {
  return entries.filter(
    (e) => !e.response.content.text && !BODYLESS_STATUS.has(e.response.status) && e.response.redirectUrl === undefined,
  );
}

async function stop() {
  const r = rec;
  if (r.stopping) return;
  r.stopping = true;
  // Como o networkidle do record.py: espera 500 ms sem evento de rede e sem corpo sendo lido.
  do await new Promise((ok) => setTimeout(ok, 500));
  while (r.inflight.size || Date.now() - r.lastEventAt < 500);
  rec = null;
  for (const tabId of r.tabs) await chrome.debugger.detach({ tabId }).catch(() => {});

  const har = { log: { version: "1.2", creator: { name: "har-recorder", version: "0.1.0" }, entries: r.entries } };
  const filename = `har-recorder/captura_${timestamp(r.startedAt)}.har`;
  const url = "data:application/json;base64," + bytesToBase64(new TextEncoder().encode(JSON.stringify(har)));
  await chrome.downloads.download({ url, filename, saveAs: false, conflictAction: "uniquify" });

  const semCorpo = audit(r.entries);
  semCorpo.forEach((e) => console.warn("sem corpo:", e.request.method, e.response.status, e.request.url));
  chrome.action.setBadgeText({ text: semCorpo.length ? "!" : "" });
  chrome.action.setTitle({
    title: `HAR Recorder: ${filename} salvo em Downloads. ${r.entries.length} entries, ${semCorpo.length} sem corpo inesperado. Clique para gravar de novo.`,
  });
  return har;
}
