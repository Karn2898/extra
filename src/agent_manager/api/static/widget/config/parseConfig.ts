import type { AgentChatConfig, AgentChatConfigInput, AgentChatMode, AgentChatPosition } from "../types";

export const DEFAULT_CONFIG: Omit<AgentChatConfig, "endpoint"> = {
  title: "Assistant",
  color: "#18181b",
  greeting: "",
  position: "bottom-right",
  avatar: "",
  mode: "floating",
  tokenUrl: "",
  requireIdentity: false,
};

const HEX_COLOR = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

export function normalizeEndpoint(value: string): string {
  return value.replace(/\/+$/, "");
}

export function safeColor(value: string | null | undefined): string {
  return value && HEX_COLOR.test(value) ? value : DEFAULT_CONFIG.color;
}

export function safePosition(value: string | null | undefined): AgentChatPosition {
  return value === "bottom-left" || value === "bottom-right" ? value : DEFAULT_CONFIG.position;
}

export function safeMode(value: string | null | undefined): AgentChatMode {
  return value === "inline" || value === "floating" ? value : DEFAULT_CONFIG.mode;
}

export function parseConfig(element: HTMLElement, scriptBaseUrl: string): AgentChatConfig {
  const endpoint = element.getAttribute("endpoint") || scriptBaseUrl;
  return {
    endpoint: normalizeEndpoint(endpoint),
    title: element.getAttribute("title") || DEFAULT_CONFIG.title,
    color: safeColor(element.getAttribute("color")),
    greeting: element.getAttribute("greeting") || DEFAULT_CONFIG.greeting,
    position: safePosition(element.getAttribute("position")),
    avatar: element.getAttribute("avatar") || DEFAULT_CONFIG.avatar,
    mode: safeMode(element.getAttribute("mode")),
    tokenUrl: element.getAttribute("token-url") || DEFAULT_CONFIG.tokenUrl,
    requireIdentity: flag(element, "require-identity"),
  };
}

/** A boolean attribute that also honours an explicit value.
 *
 * Bare presence means true, as HTML expects. But `applyConfigAttributes`
 * stringifies whatever the host put in `window.agentChatConfig`, so
 * `requireIdentity: false` arrives as `require-identity="false"` — and reading
 * presence alone would turn an explicit opt-out into an opt-in.
 */
function flag(element: HTMLElement, name: string): boolean {
  const value = element.getAttribute(name);
  return value !== null && value.toLowerCase() !== "false";
}

/** `tokenUrl` is the `token-url` attribute; HTML attributes are kebab-case. */
export function attributeName(configKey: string): string {
  return configKey.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}

export function applyConfigAttributes(element: HTMLElement, config: AgentChatConfigInput): void {
  for (const [key, value] of Object.entries(config)) {
    if (value !== undefined && value !== null) {
      element.setAttribute(attributeName(key), String(value));
    }
  }
}
