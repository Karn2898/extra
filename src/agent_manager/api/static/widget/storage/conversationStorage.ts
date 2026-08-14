/** Which chat is open, remembered per endpoint. A convenience only: the server
 * owns who may read a conversation, so an id left by a previous user is rejected
 * (403) and replaced. `logout()` clears it without the round trip.
 */
export function conversationStorageKey(endpoint: string): string {
  return `agent-chat:${endpoint}`;
}

export function getStoredConversationId(
  endpoint: string,
  storage: Storage = localStorage,
): string | null {
  return storage.getItem(conversationStorageKey(endpoint));
}

export function setStoredConversationId(
  endpoint: string,
  conversationId: string,
  storage: Storage = localStorage,
): void {
  storage.setItem(conversationStorageKey(endpoint), conversationId);
}

export function removeStoredConversationId(
  endpoint: string,
  storage: Storage = localStorage,
): void {
  storage.removeItem(conversationStorageKey(endpoint));
}
