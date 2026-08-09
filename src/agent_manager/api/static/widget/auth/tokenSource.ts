/** The bearer token the widget sends, resolved in order: a token the host
 * supplies (`tokenProvider` or `token-url`), then a visitor pass. `null` means
 * "send no bearer" — the host's session cookie speaks instead.
 *
 * A pass is only minted after a 401, so a cookie-authenticated host is never
 * handed an anonymous identity by mistake.
 */
export type TokenProvider = () => Promise<string | null>;

const PASS_ENDPOINT = "/auth/anonymous";

export function visitorPassKey(endpoint: string): string {
  return `agent-chat:pass:${endpoint}`;
}

export class TokenSource {
  private cached: string | null = null;

  constructor(
    private readonly endpoint: string,
    private readonly tokenUrl: string = "",
    private readonly provider: TokenProvider | null = null,
    private readonly storage: Storage = localStorage,
  ) {}

  async current(): Promise<string | null> {
    if (!this.cached) this.cached = (await this.fromHost()) ?? this.storedPass();
    return this.cached;
  }

  /** After a 401: whatever we sent is no good, so get another. */
  async renew(): Promise<string | null> {
    this.forget();
    this.cached = (await this.fromHost()) ?? (await this.issuePass());
    return this.cached;
  }

  /** Drop this browser's identity — a host app signing its user out. */
  forget(): void {
    this.cached = null;
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
