/** The bearer token the widget sends, resolved in order: a token the host
 * supplies (`tokenProvider` or `token-url`), then a visitor pass. `null` means
 * "send no bearer" — the host's session cookie speaks instead.
 *
 * A pass is only minted after a 401, so a cookie-authenticated host is never
 * handed an anonymous identity by mistake.
 */
export type TokenProvider = () => Promise<string | null>;

const PASS_ENDPOINT = "/auth/anonymous";
const LINK_ENDPOINT = "/auth/link";

export function visitorPassKey(endpoint: string): string {
  return `agent-chat:pass:${endpoint}`;
}

export class TokenSource {
  private cached: string | null = null;
  private pending: Promise<string | null> | null = null;

  constructor(
    private readonly endpoint: string,
    private readonly tokenUrl: string = "",
    private readonly provider: TokenProvider | null = null,
    private readonly storage: Storage = localStorage,
  ) {}

  async current(): Promise<string | null> {
    if (!this.cached) await this.resolve(() => this.storedPass());
    return this.cached;
  }

  /** After a 401: whatever we sent is no good, so get another. */
  async renew(): Promise<string | null> {
    return this.resolve(() => this.issuePass());
  }

  /** Drop this browser's identity — a host app signing its user out. */
  forget(): void {
    this.cached = null;
    this.clearPass();
  }

  /** Concurrent callers share one resolution. Without this, parallel requests
   *  each fetch a token and each hand over the visitor pass. */
  private resolve(fallback: () => string | null | Promise<string | null>): Promise<string | null> {
    this.pending ??= (async () => {
      try {
        this.cached = (await this.hostToken()) ?? (await fallback());
        return this.cached;
      } finally {
        this.pending = null;
      }
    })();
    return this.pending;
  }

  /** A host token, plus the one-time hand-off of whatever this browser chatted
   *  about before signing in. */
  private async hostToken(): Promise<string | null> {
    const token = await this.fromHost();
    if (token) await this.claimVisitorHistory(token);
    return token;
  }

  private async claimVisitorHistory(hostToken: string): Promise<void> {
    const pass = this.storedPass();
    if (!pass) return;
    try {
      const response = await fetch(`${this.endpoint}${LINK_ENDPOINT}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${hostToken}` },
        body: JSON.stringify({ anonymous_token: pass }),
      });
      // Drop the pass on any verdict, including a refusal — only a server that
      // never answered is worth asking again.
      if (response.status < 500) this.clearPass();
    } catch {
      // Offline: keep the pass so the next page load retries the hand-off.
    }
  }

  private clearPass(): void {
    try {
      this.storage.removeItem(visitorPassKey(this.endpoint));
    } catch {
      // Private-mode storage failures must not break the chat.
    }
  }

  private async fromHost(): Promise<string | null> {
    if (this.provider) return this.provider();
    if (!this.tokenUrl) return null;
    try {
      const response = await fetch(this.tokenUrl, {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return null;
      const token = (await response.json())?.token;
      return typeof token === "string" && token ? token : null;
    } catch {
      // An unreachable token endpoint is a signed-out visitor, not a crash.
      return null;
    }
  }

  private storedPass(): string | null {
    try {
      return this.storage.getItem(visitorPassKey(this.endpoint));
    } catch {
      return null;
    }
  }

  private async issuePass(): Promise<string | null> {
    try {
      const response = await fetch(`${this.endpoint}${PASS_ENDPOINT}`, { method: "POST" });
      if (!response.ok) return null;
      const token = (await response.json())?.token;
      if (typeof token !== "string" || !token) return null;
      this.storage.setItem(visitorPassKey(this.endpoint), token);
      return token;
    } catch {
      return null;
    }
  }
}
