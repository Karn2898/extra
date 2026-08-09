import { autoMountAgentChat, defineAgentChat } from "./element/defineAgentChat";

export { AgentChatClient } from "./api/AgentChatClient";
export { TokenSource, visitorPassKey, type TokenProvider } from "./auth/tokenSource";
export {
  DEFAULT_CONFIG,
  applyConfigAttributes,
  attributeName,
  parseConfig,
} from "./config/parseConfig";
export { AgentChatElement } from "./element/AgentChatElement";
export { autoMountAgentChat, defineAgentChat } from "./element/defineAgentChat";
export { escapeHtml, formatAssistantText } from "./security/renderMessage";
export {
  conversationStorageKey,
  getStoredConversationId,
  removeStoredConversationId,
  setStoredConversationId,
} from "./storage/conversationStorage";

if (typeof document !== "undefined") {
  const scriptBaseUrl = new URL(".", import.meta.url).href;
  defineAgentChat(scriptBaseUrl);
  const mount = () => autoMountAgentChat();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    setTimeout(mount, 0);
  }
}
