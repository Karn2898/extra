// Run: node src/agent_manager/api/static/widget.test.mjs
import assert from "node:assert";

class FakeClassList {
  constructor(element) {
    this.element = element;
  }
  values() {
    return this.element.className.split(/\s+/).filter(Boolean);
  }
  contains(name) {
    return this.values().includes(name);
  }
  add(name) {
    if (!this.contains(name)) this.element.className = [...this.values(), name].join(" ");
  }
  remove(name) {
    this.element.className = this.values().filter((value) => value !== name).join(" ");
  }
  toggle(name, force) {
    const enabled = force ?? !this.contains(name);
    if (enabled) this.add(name);
    else this.remove(name);
    return enabled;
  }
}

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.localName = tagName.toLowerCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.style = {};
    this.className = "";
    this.classList = new FakeClassList(this);
    this.eventListeners = new Map();
    this.textContent = "";
    this.innerHTML = "";
    this.value = "";
    this.placeholder = "";
    this.rows = 0;
    this.disabled = false;
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.isConnected = false;
  }
  setAttribute(name, value) {
    const old = this.getAttribute(name);
    this.attributes.set(name, String(value));
    if (this.constructor.observedAttributes?.includes(name)) {
      this.attributeChangedCallback?.(name, old, String(value));
    }
  }
  hasAttribute(name) {
    return this.attributes.has(name);
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }
  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    child.setConnected?.(this.isConnected);
    return child;
  }
  replaceChildren(...children) {
    for (const child of this.children) child.setConnected?.(false);
    this.children = [];
    for (const child of children) this.appendChild(child);
  }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    this.parentNode = null;
    this.setConnected?.(false);
  }
  setConnected(value) {
    if (this.isConnected === value) return;
    this.isConnected = value;
    if (value) this.connectedCallback?.();
    else this.disconnectedCallback?.();
    for (const child of this.children) child.setConnected?.(value);
    this.shadowRoot?.setConnected?.(value);
  }
  attachShadow() {
    this.shadowRoot = new FakeShadowRoot(this);
    this.shadowRoot.setConnected(this.isConnected);
    return this.shadowRoot;
  }
  addEventListener(type, handler) {
    const handlers = this.eventListeners.get(type) || new Set();
    handlers.add(handler);
    this.eventListeners.set(type, handlers);
  }
  removeEventListener(type, handler) {
    this.eventListeners.get(type)?.delete(handler);
  }
  dispatchEvent(event) {
    event.target ??= this;
    event.stopPropagation ??= () => {};
    event.preventDefault ??= () => {};
    for (const handler of this.eventListeners.get(event.type) || []) handler(event);
  }
  click() {
    this.dispatchEvent({ type: "click" });
  }
  querySelector(selector) {
    return findFirst(this, selector);
  }
  querySelectorAll(selector) {
    return findAll(this, selector);
  }
}

class FakeShadowRoot extends FakeElement {
  constructor(host) {
    super("#shadow-root");
    this.host = host;
  }
}

class FakeHTMLElement extends FakeElement {}

class FakeDocument extends FakeElement {
  constructor() {
    super("#document");
    this.readyState = "loading";
    this.body = new FakeElement("body");
  }
  createElement(tagName) {
    const Constructor = customElements.get(tagName);
    const element = Constructor ? new Constructor() : new FakeElement(tagName);
    element.localName = tagName.toLowerCase();
    element.tagName = tagName.toUpperCase();
    return element;
  }
  querySelector(selector) {
    return this.body.querySelector(selector);
  }
}

class FakeCustomElements {
  constructor() {
    this.registry = new Map();
    this.defineCount = 0;
  }
  define(name, constructor) {
    if (this.registry.has(name)) throw new Error(`already defined: ${name}`);
    this.defineCount += 1;
    this.registry.set(name, constructor);
  }
  get(name) {
    return this.registry.get(name);
  }
}

class FakeStorage {
  constructor() {
    this.values = new Map();
  }
  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }
  setItem(key, value) {
    this.values.set(key, String(value));
  }
  removeItem(key) {
    this.values.delete(key);
  }
  clear() {
    this.values.clear();
  }
}

function matches(element, selector) {
  if (selector.startsWith(".")) return element.classList.contains(selector.slice(1));
  return element.localName === selector.toLowerCase();
}

function findFirst(root, selector) {
  for (const child of root.children) {
    if (matches(child, selector)) return child;
    const found = findFirst(child, selector);
    if (found) return found;
  }
  return null;
}

function findAll(root, selector, found = []) {
  for (const child of root.children) {
    if (matches(child, selector)) found.push(child);
    findAll(child, selector, found);
  }
  return found;
}

function installDom() {
  globalThis.customElements = new FakeCustomElements();
  globalThis.HTMLElement = FakeHTMLElement;
  globalThis.document = new FakeDocument();
  globalThis.window = { agentChatConfig: undefined };
  globalThis.localStorage = new FakeStorage();
}

function resetPage() {
  document.body.replaceChildren();
  localStorage.clear();
  window.agentChatConfig = undefined;
}

function jsonResponse(body, ok = true, status = ok ? 200 : 500) {
  return { ok, status, json: async () => body };
}

async function flush() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

installDom();
const widget = await import(`./widget.js?test=${Date.now()}`);
const {
  AgentChatClient,
  TokenSource,
  applyConfigAttributes,
  visitorPassKey,
  attributeName,
  autoMountAgentChat,
  conversationStorageKey,
  defineAgentChat,
  escapeHtml,
  formatAssistantText,
  parseConfig,
} = widget;

function createChat(attrs = {}) {
  const element = document.createElement("agent-chat");
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  document.body.appendChild(element);
  return element;
}

assert.equal(escapeHtml("<script>alert(1)</script>"), "&lt;script&gt;alert(1)&lt;/script&gt;");
assert.equal(escapeHtml(`it's "quoted" & <b>`), "it&#39;s &quot;quoted&quot; &amp; &lt;b&gt;");
assert.equal(formatAssistantText("**bold** and `code`"), "<strong>bold</strong> and <code>code</code>");
assert.equal(formatAssistantText("line1\nline2"), "line1\nline2");
assert.ok(formatAssistantText("```\nconst x = 1;\n```").includes("<pre><code>const x = 1;</code></pre>"));
assert.equal(formatAssistantText("<img onerror=alert(1)>"), "&lt;img onerror=alert(1)&gt;");
assert.equal(formatAssistantText("<b>raw</b>"), "&lt;b&gt;raw&lt;/b&gt;");

assert.ok(customElements.get("agent-chat"), "custom element is registered");
const definesBefore = customElements.defineCount;
defineAgentChat("https://ignored.example");
assert.equal(customElements.defineCount, definesBefore, "defineAgentChat is idempotent");

{
  const element = new FakeElement("agent-chat");
  const cfg = parseConfig(element, "https://widget.example");
  assert.deepEqual(cfg, {
    endpoint: "https://widget.example",
    title: "Assistant",
    color: "#18181b",
    greeting: "",
    position: "bottom-right",
    avatar: "",
    mode: "floating",
    tokenUrl: "",
    requireIdentity: false,
  });
}

{
  const element = new FakeElement("agent-chat");
  element.setAttribute("endpoint", "https://api.example/");
  element.setAttribute("title", "Support");
  element.setAttribute("color", "#7c3aed");
  element.setAttribute("greeting", "Hi");
  element.setAttribute("position", "bottom-left");
  element.setAttribute("avatar", "https://cdn.example/a.png");
  element.setAttribute("mode", "inline");
  element.setAttribute("token-url", "/agent-chat/token");
  const cfg = parseConfig(element, "https://widget.example");
  assert.equal(cfg.endpoint, "https://api.example");
  assert.equal(cfg.title, "Support");
  assert.equal(cfg.color, "#7c3aed");
  assert.equal(cfg.greeting, "Hi");
  assert.equal(cfg.position, "bottom-left");
  assert.equal(cfg.avatar, "https://cdn.example/a.png");
  assert.equal(cfg.mode, "inline");
  assert.equal(cfg.tokenUrl, "/agent-chat/token");
}

assert.equal(attributeName("tokenUrl"), "token-url");

// Proxied under the host's site, the script's own directory is the API base —
// the deployment that authenticates by the host cookie needs no `endpoint`.
{
  const element = new FakeElement("agent-chat");
  const cfg = parseConfig(element, "https://app.acme.com/agents/");
  assert.equal(cfg.endpoint, "https://app.acme.com/agents");
}

{
  const element = new FakeElement("agent-chat");
  element.setAttribute("color", "url(javascript:alert(1))");
  element.setAttribute("position", "top-left");
  element.setAttribute("mode", "sideways");
  const cfg = parseConfig(element, "https://widget.example");
  assert.equal(cfg.color, "#18181b");
  assert.equal(cfg.position, "bottom-right");
  assert.equal(cfg.mode, "floating");
}

resetPage();
window.agentChatConfig = { title: "Auto", color: "#111111", endpoint: "https://api.example/" };
autoMountAgentChat();
assert.equal(document.body.querySelectorAll("agent-chat").length, 1);
const mounted = document.body.querySelector("agent-chat");
assert.equal(mounted.getAttribute("title"), "Auto");
assert.equal(mounted.getAttribute("endpoint"), "https://api.example/");
autoMountAgentChat();
assert.equal(document.body.querySelectorAll("agent-chat").length, 1, "auto-mount does not duplicate");

resetPage();
const fetchCalls = [];
globalThis.fetch = async (url, options = {}) => {
  fetchCalls.push({ url, options });
  if (url.endsWith("/conversations")) return jsonResponse({ conversation_id: "conv-1" });
  if (url.endsWith("/messages")) return jsonResponse({ answer: "hello back" });
  if (url.endsWith("/runs/run-1/approvals/approval-1/decision")) {
    return jsonResponse({ answer: "approved", status: "completed", pending_approval: null });
  }
  throw new Error(`unexpected fetch: ${url}`);
};
let client = new AgentChatClient("https://api.example", new TokenSource("https://api.example"));
const conversationId = await client.createConversation();
assert.equal(conversationId, "conv-1");
const sendResponse = await client.sendMessage(conversationId, "hello");
assert.equal(fetchCalls[0].url, "https://api.example/conversations");
assert.equal(fetchCalls[1].url, "https://api.example/conversations/conv-1/messages");
assert.equal(JSON.parse(fetchCalls[1].options.body).message, "hello");
assert.equal(sendResponse.answer, "hello back");
const approvalResponse = await client.decideApproval(
  conversationId,
  "run-1",
  "approval-1",
  "allow_for_session",
);
assert.equal(
  fetchCalls[2].url,
  "https://api.example/conversations/conv-1/runs/run-1/approvals/approval-1/decision",
);
assert.equal(JSON.parse(fetchCalls[2].options.body).decision, "allow_for_session");
assert.equal(approvalResponse.answer, "approved");

resetPage();
globalThis.fetch = async (url) => {
  if (url.endsWith("/conv-stored/messages")) {
    return jsonResponse([{ role: "assistant", content: "old answer" }]);
  }
  throw new Error(`unexpected fetch: ${url}`);
};
client = new AgentChatClient("https://api.example", new TokenSource("https://api.example"));
const history = await client.getMessages("conv-stored");
assert.deepEqual(history, [{ role: "assistant", content: "old answer" }]);

resetPage();
globalThis.fetch = async (url) => {
  if (url.endsWith("/conversations")) return jsonResponse({ conversation_id: "conv-2" });
  return jsonResponse({}, false, 500);
};
client = new AgentChatClient("https://api.example", new TokenSource("https://api.example"));
assert.ok(client);
await assert.rejects(() => client.sendMessage("conv-2", "break"), /HTTP 500/);


// --- identity ------------------------------------------------------------

const authHeader = (call) => call.options.headers.Authorization;

// A same-origin deployment authenticates by the host's own cookie: no bearer to
// send, but the request must still carry credentials.
resetPage();
let calls = [];
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url, options });
  return jsonResponse({ conversation_id: "conv-cookie" });
};
await new AgentChatClient("https://api.example", new TokenSource("https://api.example")).createConversation();
assert.equal(authHeader(calls[0]), undefined, "no bearer when relying on the host cookie");
assert.equal(calls[0].options.credentials, "include");

// A host that exposes a token endpoint has it fetched once and sent as a bearer.
resetPage();
calls = [];
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url, options });
  if (url === "/agent-chat/token") return jsonResponse({ token: "host-token" });
  return jsonResponse({ conversation_id: "conv-host" });
};
const hosted = new AgentChatClient(
  "https://api.example",
  new TokenSource("https://api.example", { tokenUrl: "/agent-chat/token" }),
);
await hosted.createConversation();
await hosted.createConversation();
assert.equal(calls.filter((c) => c.url === "/agent-chat/token").length, 1, "token is cached");
assert.equal(authHeader(calls[1]), "Bearer host-token");

// No host identity at all: the first 401 buys a visitor pass, and the rejected
// request is replayed with it.
resetPage();
calls = [];
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url, options });
  if (url.endsWith("/auth/anonymous")) return jsonResponse({ token: "visitor-pass" });
  if (!authHeader({ options })) return jsonResponse({}, false, 401);
  return jsonResponse({ conversation_id: "conv-visitor" });
};
const visitorTokens = new TokenSource("https://api.example");
const visitor = new AgentChatClient("https://api.example", visitorTokens);
assert.equal(await visitor.createConversation(), "conv-visitor");
assert.deepEqual(
  calls.map((c) => c.url),
  [
    "https://api.example/conversations",
    "https://api.example/auth/anonymous",
    "https://api.example/conversations",
  ],
);
assert.equal(localStorage.getItem(visitorPassKey("https://api.example")), "visitor-pass");

visitorTokens.forget();
assert.equal(localStorage.getItem(visitorPassKey("https://api.example")), null);

// Signing in hands the pre-login conversations to the account, once.
resetPage();
calls = [];
localStorage.setItem(visitorPassKey("https://api.example"), "old-pass");
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url, options });
  if (url === "/agent-chat/token") return jsonResponse({ token: "host-token" });
  if (url.endsWith("/auth/link")) return jsonResponse({ conversations_moved: 2 });
  return jsonResponse({ conversation_id: "conv-merged" });
};
const signedIn = new AgentChatClient(
  "https://api.example",
  new TokenSource("https://api.example", { tokenUrl: "/agent-chat/token" }),
);
await signedIn.createConversation();

const link = calls.find((c) => c.url.endsWith("/auth/link"));
assert.ok(link, "the visitor pass is handed over on sign-in");
assert.equal(authHeader(link), "Bearer host-token");
assert.equal(JSON.parse(link.options.body).anonymous_token, "old-pass");
assert.equal(
  localStorage.getItem(visitorPassKey("https://api.example")),
  null,
  "a handed-over pass is not offered twice",
);

// Parallel requests share one resolution: one token fetch, one hand-over.
resetPage();
calls = [];
localStorage.setItem(visitorPassKey("https://api.example"), "old-pass");
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url, options });
  await new Promise((resolve) => setTimeout(resolve, 0));
  if (url === "/agent-chat/token") return jsonResponse({ token: "host-token" });
  if (url.endsWith("/auth/link")) return jsonResponse({ conversations_moved: 1 });
  return jsonResponse({ conversation_id: "conv-parallel" });
};
const shared = new AgentChatClient(
  "https://api.example",
  new TokenSource("https://api.example", { tokenUrl: "/agent-chat/token" }),
);
await Promise.all([shared.createConversation(), shared.createConversation()]);
assert.equal(calls.filter((c) => c.url === "/agent-chat/token").length, 1);
assert.equal(calls.filter((c) => c.url.endsWith("/auth/link")).length, 1);

// A server that never answered keeps the pass, so the next load retries.
resetPage();
localStorage.setItem(visitorPassKey("https://api.example"), "kept-pass");
globalThis.fetch = async (url) => {
  if (url === "/agent-chat/token") return jsonResponse({ token: "host-token" });
  if (url.endsWith("/auth/link")) throw new Error("offline");
  return jsonResponse({ conversation_id: "conv-1" });
};
await new AgentChatClient(
  "https://api.example",
  new TokenSource("https://api.example", { tokenUrl: "/agent-chat/token" }),
).createConversation();
assert.equal(localStorage.getItem(visitorPassKey("https://api.example")), "kept-pass");


// A configured token-url that fails is reported, not swallowed — the silence
// here is what made a broken integration look like a working anonymous chat.
resetPage();
let failures = [];
globalThis.fetch = async (url) => {
  if (url === "/agent-chat/token") return jsonResponse({}, false, 404);
  if (url.endsWith("/auth/anonymous")) return jsonResponse({ token: "pass" });
  return jsonResponse({ conversation_id: "c1" });
};
const reporting = new TokenSource("https://api.example", {
  tokenUrl: "/agent-chat/token",
  onIdentityFailure: (f) => failures.push(f),
});
assert.equal(await reporting.renew(), "pass", "still falls back by default");
assert.deepEqual(failures, [{ reason: "unreachable", status: 404, url: "/agent-chat/token" }]);

// 401 is the ordinary signed-out case, reported but distinguishable.
resetPage();
failures = [];
globalThis.fetch = async (url) => {
  if (url === "/agent-chat/token") return jsonResponse({}, false, 401);
  if (url.endsWith("/auth/anonymous")) return jsonResponse({ token: "pass" });
  return jsonResponse({});
};
await new TokenSource("https://api.example", {
  tokenUrl: "/agent-chat/token",
  onIdentityFailure: (f) => failures.push(f),
}).renew();
assert.equal(failures[0].reason, "unauthorized");

// An endpoint answering 200 with the wrong shape is an integration bug too.
resetPage();
failures = [];
globalThis.fetch = async (url) => {
  if (url === "/agent-chat/token") return jsonResponse({ access_token: "wrong-key" });
  if (url.endsWith("/auth/anonymous")) return jsonResponse({ token: "pass" });
  return jsonResponse({});
};
await new TokenSource("https://api.example", {
  tokenUrl: "/agent-chat/token",
  onIdentityFailure: (f) => failures.push(f),
}).renew();
assert.equal(failures[0].reason, "malformed");

// require-identity: no anonymous consolation prize.
resetPage();
let mintedPass = false;
globalThis.fetch = async (url) => {
  if (url === "/agent-chat/token") return jsonResponse({}, false, 401);
  if (url.endsWith("/auth/anonymous")) {
    mintedPass = true;
    return jsonResponse({ token: "pass" });
  }
  return jsonResponse({});
};
const strict = new TokenSource("https://api.example", {
  tokenUrl: "/agent-chat/token",
  requireIdentity: true,
});
assert.equal(await strict.renew(), null, "no token rather than an anonymous one");
assert.equal(mintedPass, false, "never asks for a visitor pass");


// require-identity is opt-in in BOTH directions. The generic config mapper
// stringifies booleans, so `requireIdentity: false` arrives as the string
// "false" — reading presence alone would flip an explicit opt-out into opt-in
// and make a login-less product fail closed.
{
  const absent = new FakeElement("agent-chat");
  assert.equal(parseConfig(absent, "https://w.example").requireIdentity, false);

  const bare = new FakeElement("agent-chat");
  bare.setAttribute("require-identity", "");
  assert.equal(parseConfig(bare, "https://w.example").requireIdentity, true);

  const explicitTrue = new FakeElement("agent-chat");
  explicitTrue.setAttribute("require-identity", "true");
  assert.equal(parseConfig(explicitTrue, "https://w.example").requireIdentity, true);

  const explicitFalse = new FakeElement("agent-chat");
  explicitFalse.setAttribute("require-identity", "false");
  assert.equal(
    parseConfig(explicitFalse, "https://w.example").requireIdentity,
    false,
    'require-identity="false" must stay false',
  );

  // ...and end to end through the mapper the auto-mount path uses. A boolean
  // that is off must not appear in the markup at all: HTML says an attribute
  // that exists is on, whatever its value.
  const mapped = new FakeElement("agent-chat");
  applyConfigAttributes(mapped, { requireIdentity: false });
  assert.equal(mapped.hasAttribute("require-identity"), false, "off means absent");
  assert.equal(
    parseConfig(mapped, "https://w.example").requireIdentity,
    false,
    "window.agentChatConfig { requireIdentity: false } must not fail closed",
  );

  const mappedOn = new FakeElement("agent-chat");
  applyConfigAttributes(mappedOn, { requireIdentity: true });
  assert.equal(mappedOn.getAttribute("require-identity"), "", "on is bare presence");
  assert.equal(parseConfig(mappedOn, "https://w.example").requireIdentity, true);
}



// Signing in without a page reload must switch identity — the cached anonymous
// pass otherwise survives the login and the user sees a stranger's empty chat.
{
  resetPage();
  localStorage.setItem(visitorPassKey("https://api.example"), "old-pass");
  let loggedIn = false;
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, auth: options.headers?.Authorization });
    if (url === "/agent-chat/token") {
      return loggedIn ? jsonResponse({ token: "host-token" }) : jsonResponse({}, false, 401);
    }
    if (url.endsWith("/auth/anonymous")) return jsonResponse({ token: "anon-pass" });
    if (url.endsWith("/auth/link")) return jsonResponse({ conversations_moved: 1 });
    return jsonResponse({ conversation_id: "c1" });
  };
  const tokens = new TokenSource("https://api.example", { tokenUrl: "/agent-chat/token" });
  const client = new AgentChatClient("https://api.example", tokens);

  await client.createConversation();
  const sentWhileSignedOut = calls.filter((c) => c.url.endsWith("/conversations")).pop().auth;
  assert.equal(sentWhileSignedOut, "Bearer old-pass", "anonymous before login");

  loggedIn = true;
  tokens.reset(); // what refreshIdentity() does
  await client.createConversation();
  const sentAfterLogin = calls.filter((c) => c.url.endsWith("/conversations")).pop().auth;
  assert.equal(sentAfterLogin, "Bearer host-token", "the signed-in user, not the visitor");

  // ...and the pass survived long enough to be handed over.
  assert.ok(
    calls.some((c) => c.url.endsWith("/auth/link")),
    "pre-login conversations are merged, not stranded",
  );
}

// reset() keeps the visitor pass; only forget() discards it. Getting this
// backwards silently throws away the conversations the merge exists to rescue.
{
  resetPage();
  const key = visitorPassKey("https://api.example");
  localStorage.setItem(key, "pass");
  const tokens = new TokenSource("https://api.example");

  tokens.reset();
  assert.equal(localStorage.getItem(key), "pass", "reset keeps the pass");

  tokens.forget();
  assert.equal(localStorage.getItem(key), null, "forget drops it");
}

console.log("widget self-check: OK");
