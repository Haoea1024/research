export interface ServerEvent {
  id: number;
  event: "block" | "progress" | "error" | "finished";
  data: Record<string, unknown>;
}

export async function consumeTranslationStream(
  paperId: string,
  runId: string,
  onEvent: (event: ServerEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  let lastEventId: number | undefined;
  let finished = false;
  while (!finished && !signal.aborted) {
    const headers: HeadersInit = { Accept: "text/event-stream" };
    if (lastEventId !== undefined) headers["Last-Event-ID"] = String(lastEventId);
    const response = await fetch(
      `/api/papers/${encodeURIComponent(paperId)}/translate/stream?run_id=${encodeURIComponent(runId)}`,
      { headers, signal },
    );
    if (!response.ok || !response.body) {
      throw new Error(`Translation stream failed (${response.status})`);
    }
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      buffer += value ?? "";
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const event = parseFrame(frame);
        if (!event) continue;
        if (event.id > 0) lastEventId = event.id;
        onEvent(event);
        if (event.event === "finished") finished = true;
      }
      if (done || finished) break;
    }
    if (!finished && !signal.aborted) await abortableDelay(300, signal);
  }
}

export function parseFrame(frame: string): ServerEvent | null {
  let id = 0;
  let event = "message";
  const data: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("id:")) id = Number(line.slice(3).trim());
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!["block", "progress", "error", "finished"].includes(event) || data.length === 0) {
    return null;
  }
  return { id, event: event as ServerEvent["event"], data: JSON.parse(data.join("\n")) };
}

function abortableDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(resolve, milliseconds);
    signal.addEventListener("abort", () => {
      window.clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}
