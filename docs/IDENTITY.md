# Identity — how it works

How to *use* this is [docs/identity.mdx](identity.mdx). This document is the
design: why it works the way it does, and what to know before changing it.

## The problem

Extra is embedded in someone else's product, so it cannot authenticate a user
itself — the host already did. It can only *verify* an identity the host signs.

Before this existed, the caller was `X-Agent-Chat-User`, a header the browser set
for itself:

```bash
curl -H 'X-Agent-Chat-User: alice' .../conversations   # returned Alice's chats
```

Conversation ownership was already enforced; the id it compared just wasn't
proven. That header is gone, and every route now requires a signed token.

## Two issuers, one verifier

| Issuer | Token | Verified with |
|---|---|---|
| The host product | its own session JWT, or one it mints for us | `AGENT_AUTH_SECRET` |
| The manager | a visitor pass | a key derived from that secret |

`IdentityResolver` routes on the `kid` header, which is only a hint — the
signature check that follows is what decides. Passes are signed with a *derived*
key rather than the host's own, so a host that can mint tokens still cannot mint
passes.

`TokenVerifier` never names an algorithm. It takes them from a `KeySource`:

```python
class KeySource(Protocol):
    @property
    def algorithms(self) -> tuple[str, ...]: ...
    def key_for(self, header: Mapping[str, Any]) -> Any: ...
```

Only `StaticSecretKeySource` (HS256) ships. RS256/ES256 is a new implementation
with a public key; JWKS is one that caches by `kid` — which is why `key_for`
receives the header. Nothing else changes.

## The browser constraint

Host session cookies are httpOnly: the widget cannot read them, and the browser
will not send them cross-origin. That single fact produces the three modes:
same-origin needs no code, cross-origin needs a token endpoint, and no-login
needs neither.

## How ids map

`conversation_users.user_id` is a 64-character primary key and a foreign-key
target, while a host subject may be an email or a long OIDC subject. So:

- `user_id = "ext:" + sha256(subject)[:32]` — fixed width, deterministic.
- The raw subject is stored in the indexed `external_user_id` column, so support
  lookups and debugging use the readable value.
- Visitor passes use `anon:<uuid>`, a separate namespace, so a host id can never
  collide with one.

Users are created on first use. There is no mapping table and nothing to sync.

## Visitor passes and the merge

A pass is a signed token naming one random id. Possession is what grants access,
so guessing another visitor's id gets you nothing.

When a visitor signs in, the widget posts its pass and its new token to
`/auth/link`. Both are verified — the pass says *which* conversations, the
caller's token says *who* is adopting them — and the sessions change owner.

Claiming a visitor is a conditional `UPDATE` on `linked_to_user_id`, not a read
then a write: two tabs signing in at once would otherwise both pass a read check
and hand the same conversations to two accounts. A replayed pass moves nothing.

Stealing a pass already grants full access to those conversations, so being able
to link one adds no privilege.

## Securing the host's token endpoint

In `mint` mode this endpoint is the front door to every identity in the product:

- **Behind the existing login.** It takes no parameters; the caller proves who
  they are by being logged in. Signed out → `401`, and the widget falls back to a
  pass.
- **Sign the session's user, never a request value.** `sub: req.user.id`, not
  `sub: req.query.user`.
- **No permissive CORS, and `Cache-Control: no-store`.** Another origin can send
  the request but cannot read the reply — unless `Access-Control-Allow-Origin`
  is added, which would give tokens away.

## Deliberate gaps

- `/auth/anonymous` is unauthenticated and unthrottled. It writes no rows, so it
  is cheap, but it is an unbounded mint — rate limit at the edge if it matters.
- `host_token` mode does not cap token lifetime; that lifetime is the host's
  decision.
- With no secret configured at all, visitor passes are signed with an ephemeral
  key and do not survive a restart. A warning is logged.
- `run_context.auth_context` is still unpopulated: verified roles and claims do
  not reach agents yet, so `protected` nodes remain unenforced.

## Development

```bash
AGENT_AUTH_MODE=mint AGENT_AUTH_SECRET=$SECRET agentctl token --user alice
curl http://localhost:8100/conversations -H "Authorization: Bearer $TOKEN"
```
