/** UUID v4 generator that also works outside secure contexts.
 *
 * `crypto.randomUUID()` throws on plain http origins other than localhost
 * (browsers restrict it to secure contexts). `crypto.getRandomValues()` has
 * no such restriction, so build a v4 UUID from it when `randomUUID` is
 * unavailable.
 */
export function randomId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
