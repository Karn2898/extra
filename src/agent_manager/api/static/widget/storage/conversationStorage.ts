/** Which chat is open, remembered per endpoint *and* per user.
 *
 * Scoping by user matters: one browser can serve several people (a shared
 * machine, or a host app that signs a new user in via `<agent-chat user="...">`).
 * Keyed by endpoint alone, the next user would resume the previous user's
 * conversation.
 */
export function conversationStorageKey(endpoint: string, userId: string): string {
  return `agent-chat:${endpoint}:${userId}`;
}

export function getStoredConversationId(
  endpoint: string,
  userId: string,
  storage: Storage = localStorage,
): string | null {
  return storage.getItem(conversationStorageKey(endpoint, userId));
}

export function setStoredConversationId(
  endpoint: string,
  userId: string,
  conversationId: string,
  storage: Storage = localStorage,
): void {
  storage.setItem(conversationStorageKey(endpoint, userId), conversationId);
}

export function removeStoredConversationId(
  endpoint: string,
  userId: string,
  storage: Storage = localStorage,
): void {
  storage.removeItem(conversationStorageKey(endpoint, userId));
}

export function getOrCreateUserId(endpoint: string, storage: Storage = localStorage): string {
  const key = `agent-chat:user:${endpoint}`;
  let id = storage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    storage.setItem(key, id);
  }
  return id;
}
