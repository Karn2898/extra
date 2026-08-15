import { createRoot, type Root } from "react-dom/client";

import { AgentChatClient } from "../api/AgentChatClient";
import { TokenSource, type IdentityFailure, type TokenProvider } from "../auth/tokenSource";
import { parseConfig } from "../config/parseConfig";
import { AgentChatApp } from "../react/AgentChatApp";
import { removeStoredConversationId } from "../storage/conversationStorage";
import { styles } from "../styles/styles";
import type {
  AgentChatAnswerDetail,
  AgentChatConfig,
  AgentChatIdentityErrorDetail,
} from "../types";

let nextWidgetId = 0;

export class AgentChatElement extends HTMLElement {
  static get observedAttributes(): string[] {
    return [
      "endpoint",
      "title",
      "color",
      "greeting",
      "position",
      "avatar",
      "mode",
      "token-url",
      "require-identity",
    ];
  }

  /** For a host holding its token in memory instead of exposing a `token-url`.
   *  Assign before the element connects, or re-render after. */
  tokenProvider: TokenProvider | null = null;

  private config!: AgentChatConfig;
  private tokens!: TokenSource;
  private client!: AgentChatClient;
  private connected = false;
  private reactRoot: Root | null = null;
  private instanceKey = 0;
  private readonly widgetId = `agent-chat-${++nextWidgetId}`;
  private readonly panelId = `${this.widgetId}-panel`;
  private readonly titleId = `${this.widgetId}-title`;

  constructor(private readonly scriptBaseUrl: string = defaultScriptBaseUrl()) {
    super();
  }

  connectedCallback(): void {
    if (this.connected) return;
    this.connected = true;
    this.configure();
    this.render();
  }

  disconnectedCallback(): void {
    this.reactRoot?.unmount();
    this.reactRoot = null;
    this.connected = false;
  }

  attributeChangedCallback(_name: string, oldValue: string | null, newValue: string | null): void {
    if (!this.connected || oldValue === newValue) return;
    const previousEndpoint = this.config?.endpoint;
    this.configure();
    if (previousEndpoint && previousEndpoint !== this.config.endpoint) this.instanceKey += 1;
    this.render();
  }

  /** Forget this browser's identity and its open thread, so the next person on
   *  this machine starts clean. Call it when the host signs a user in or out. */
  logout(): void {
    this.tokens?.forget();
    if (this.config) removeStoredConversationId(this.config.endpoint);
    this.instanceKey += 1;
    if (this.connected) this.render();
  }

  private configure(): void {
    this.config = parseConfig(this, this.scriptBaseUrl);
    this.tokens = new TokenSource(this.config.endpoint, {
      tokenUrl: this.config.tokenUrl,
      provider: this.tokenProvider,
      requireIdentity: this.config.requireIdentity,
      onIdentityFailure: (failure) => this.emitIdentityFailure(failure),
    });
    this.client = new AgentChatClient(this.config.endpoint, this.tokens);
  }

  /** A configured identity that could not be obtained is reported, never
   *  swallowed: an unreachable `token-url` otherwise looks exactly like a
   *  working anonymous chat, which is how a broken integration ships. */
  private emitIdentityFailure(failure: IdentityFailure): void {
    const anonymousFallbackEnabled = !this.config.requireIdentity;
    const detail: AgentChatIdentityErrorDetail = { ...failure, anonymousFallbackEnabled };
    if (failure.reason !== "unauthorized") {
      console.warn(
        `[agent-chat] could not obtain an identity from ${failure.url}` +
          `${failure.status ? ` (HTTP ${failure.status})` : ""}: ${failure.reason}.` +
          `${anonymousFallbackEnabled ? " May fall back to an anonymous visitor." : ""}`,
      );
    }
    try {
      this.dispatchEvent(
        new CustomEvent<AgentChatIdentityErrorDetail>("agent-chat:identity-error", {
          detail,
          bubbles: true,
          composed: true,
        }),
      );
    } catch {
      // Reporting must never break the chat.
    }
  }

  private render(): void {
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    this.reactRoot?.unmount();
    this.reactRoot = null;
    root.replaceChildren();

    const style = document.createElement("style");
    style.textContent = styles(this.config);
    root.appendChild(style);

    const mount = document.createElement("div");
    mount.className = "react-mount";
    root.appendChild(mount);
    this.reactRoot = createRoot(mount);
    this.reactRoot.render(
      <AgentChatApp
        key={this.instanceKey}
        client={this.client}
        config={this.config}
        onAnswer={(detail) => this.emitAnswer(detail)}
        panelId={this.panelId}
        titleId={this.titleId}
      />,
    );
  }

  /**
   * Surface safe routing metadata (the agent graph path and any tools used) so
   * host pages can observe which agent/sub-agent handled a turn. This does not
   * expose reasoning or hidden content.
   */
  private emitAnswer(detail: AgentChatAnswerDetail): void {
    try {
      if (detail.visited.length) {
        console.debug?.("[agent-chat] route:", detail.visited.join(" -> "), detail.used_tools);
      }
      if (typeof CustomEvent === "function" && typeof this.dispatchEvent === "function") {
        this.dispatchEvent(
          new CustomEvent<AgentChatAnswerDetail>("agent-chat:answer", {
            detail,
            bubbles: true,
            composed: true,
          }),
        );
      }
    } catch {
      // Observability must never break the chat flow.
    }
  }
}

/** The manager serves this script, so its own directory is the API base — path
 *  prefix included, which `.origin` would drop for a deployment proxied under
 *  the host's site at e.g. /agents/widget.js. */
function defaultScriptBaseUrl(): string {
  return new URL(".", import.meta.url).href;
}
