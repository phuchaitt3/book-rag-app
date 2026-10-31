import type { ChatEvent } from "./client";

// Reads a server-sent-events body (`event: x\ndata: {...}\n\n`) and yields each parsed event.
// `EventSource` cannot send a POST body, so the chat answer is read from `fetch` instead.
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<ChatEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const event = parseEvent(buffer.slice(0, end));
      buffer = buffer.slice(end + 2);
      if (event) yield event;
    }
  }
}

function parseEvent(block: string): ChatEvent | null {
  let name = "";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!name || data.length === 0) return null;
  return { event: name, data: JSON.parse(data.join("\n")) } as ChatEvent;
}
