# Identity

Extra is embedded in someone else's product, so it cannot authenticate a user
itself — the host already did that. What it needs is for the host to **attest**
who the caller is, in a way the manager can verify.

Every conversation is owned by exactly one caller. The conversation id is not a
credential: knowing it grants nothing.

## The constraint that decides your integration

Host session tokens normally live in **httpOnly cookies**. The widget's
JavaScript cannot read them, and the browser will not send them cross-origin. So:

- **Manager served from the host's own origin** → the cookie arrives on our
  requests automatically → **no host code at all**.
- **Manager on a different origin** → the host must expose a token endpoint.
  There is no way around this; it is the browser's rule, not ours.

## Mode 1 — `host_token`: verify the host's own session token

The operator adds a proxy rule (`https://app.acme.com/agents/*` → the manager
container) and three environment variables:

```bash
AGENT_AUTH_MODE=host_token
AGENT_AUTH_SECRET=${THE_HOSTS_OWN_JWT_SECRET}
AGENT_AUTH_CLAIM_USER_ID=id      # which claim carries their user id
AGENT_AUTH_COOKIE=token          # name of their session cookie
```

```html
<script type="module" src="/agents/widget.js"></script>
<agent-chat></agent-chat>
```

The widget calls back to the directory it was served from, so the proxy prefix
needs no repeating. No endpoint, no SDK, no user import, and no change to
`agents.yml`.

### Worked example: Open WebUI

Open WebUI signs its session JWT with `WEBUI_SECRET_KEY` (HS256) and stores it in
an httpOnly `token` cookie. Proxied under its origin, the configuration above is
the whole integration — an ops change, not a code change. The same shape fits
Django, Rails, or anything else that issues a session JWT.

## Mode 2 — `mint`: the host mints a token for us

Use this when the manager is cross-origin, or when you want short-lived tokens
carrying claims the session token does not have (`plan`, `tenant`, `locale`).

```bash
AGENT_AUTH_MODE=mint
AGENT_AUTH_SECRET=<a shared secret, 32+ characters>
```

One endpoint in the host backend — it runs behind the host's existing login, so
Extra never sees a password or a session table:

```js
app.get("/agent-chat/token", requireLogin, (req, res) => {
  res.set("Cache-Control", "no-store");
  res.json({
    token: jwt.sign(
      { sub: req.user.id, email: req.user.email, roles: req.user.roles },
      process.env.AGENT_CHAT_SECRET,
      { expiresIn: "1h" },
    ),
  });
});
```

```html
<agent-chat endpoint="https://agents.acme.com" token-url="/agent-chat/token"></agent-chat>
```

### Securing the token endpoint

It is the front door to every identity in your product, so:

- **Keep it behind your existing login.** It takes no parameters; the caller
  proves who they are by being logged in. Signed out, return 401 — the widget
  falls back to a visitor pass on its own.
- **Sign the session's user, never a request value.** `sub: req.user.id` is
  correct; `sub: req.query.user` would let anyone mint a token as anyone.
- **No permissive CORS on it, and `Cache-Control: no-store`.** Another origin can
  send the request but cannot read the reply — unless you add
  `Access-Control-Allow-Origin`, which would hand your users' tokens away. The
  no-store header keeps a shared cache from serving one user's token to another.

Tokens are capped at `AGENT_AUTH_MAX_TTL_SECONDS` (default one hour). A single
sign-on app that holds its token in memory can skip `token-url` and assign a
provider instead:

```js
document.querySelector("agent-chat").tokenProvider = async () => store.accessToken;
```

## Mode 3 — `anonymous`: products with no login

The default. Nothing to configure and nothing for the host to build: the widget
asks the manager for a **visitor pass** and keeps it in `localStorage`. Each
browser is its own user.

A pass is signed, so a visitor cannot reach another visitor's conversations by
guessing an id — this is isolation, not just separation.

Set `AGENT_AUTH_ANONYMOUS_SECRET` in production. Without it the manager derives
the pass key from `AGENT_AUTH_SECRET`, or — if neither is set — signs with an
ephemeral key, and every restart invalidates outstanding passes.

## What happens at runtime

```text
widget call → bearer token (minted or a visitor pass), or the host's cookie
manager    → verify the signature → the user id claim is genuinely theirs
           → user_id = "ext:<digest>", created on first use
401        → the widget renews its token once and retries; that is the whole
             refresh story
host session gone → the token endpoint 401s → the widget falls back to a pass
```

## How a host user id maps to ours

There is no mapping table to maintain and nothing to synchronise:

- The mapped claim (`sub` by default) is hashed into
  `user_id = "ext:" + sha256(subject)[:32]`, because `conversation_users.user_id`
  is a 64-character primary key and a host subject may be an email address or a
  long OIDC subject.
- The raw value is stored alongside it in the indexed `external_user_id` column,
  so support lookups and debugging use the readable id.
- A user exists in Extra the first moment they send a message.
- The same host id on a laptop and a phone yields the same conversations.

Visitor passes use the separate `anon:` namespace, so a host id can never
collide with one.

## Signing in and out

```js
document.querySelector("agent-chat").logout();
```

Clears the stored token and the remembered thread. On sign-**out** it is not
strictly required — a stored conversation belonging to someone else is rejected
and replaced — but it avoids the round trip and the flash of a stale thread.

On sign-**in** it matters more. The widget resolves its identity host-token-first
on every page load, so a normal navigation after login picks up the new user by
itself. A single-page app that signs a user in without reloading should call
`logout()` at that moment, or the widget keeps using the visitor pass it already
holds for the rest of the session.

## Rotating the secret

Tokens are verified against `AGENT_AUTH_SECRET` at request time, so rotating it
invalidates every outstanding token: users' widgets fetch a new one on their next
401 and continue. Visitor passes derived from the old secret are invalidated too
unless `AGENT_AUTH_ANONYMOUS_SECRET` is set explicitly.

## Extending verification

`TokenVerifier` never names an algorithm. It takes them from a `KeySource`,
which is the one thing that differs between HS256, RS256/ES256, and JWKS:

```python
class KeySource(Protocol):
    @property
    def algorithms(self) -> tuple[str, ...]: ...
    def key_for(self, header: Mapping[str, Any]) -> Any: ...
```

Today only `StaticSecretKeySource` ships. Supporting an asymmetric issuer means
adding an implementation — a public key, or a JWKS fetch cached by `kid`, which
is why `key_for` receives the token header — and changing nothing else.

## Development

The manager trusts no client-supplied identity, so use a minted token to drive
the API by hand:

```bash
AGENT_AUTH_MODE=mint AGENT_AUTH_SECRET=$SECRET agentctl token --user alice
curl http://localhost:8100/conversations -H "Authorization: Bearer $TOKEN"
```
