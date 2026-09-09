import { useEffect, useMemo, useRef } from "react";
import katex from "katex";

type Token =
  | { kind: "text"; value: string }
  | { kind: "math"; value: string; display: boolean }
  | { kind: "sup"; value: string };

const MIXED_TOKEN = /(\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$(?!\$)(?:\\.|[^$\\])+\$|<sup>[^<>]*<\/sup>)/gi;

function tokenize(value: string): Token[] {
  const tokens: Token[] = [];
  let cursor = 0;
  for (const match of value.matchAll(MIXED_TOKEN)) {
    const index = match.index ?? 0;
    if (index > cursor) tokens.push({ kind: "text", value: value.slice(cursor, index) });
    const raw = match[0];
    if (raw.toLowerCase().startsWith("<sup>")) {
      tokens.push({ kind: "sup", value: raw.slice(5, -6) });
    } else if (raw.startsWith("\\[")) {
      tokens.push({ kind: "math", value: raw.slice(2, -2), display: true });
    } else if (raw.startsWith("\\(")) {
      tokens.push({ kind: "math", value: raw.slice(2, -2), display: false });
    } else {
      tokens.push({ kind: "math", value: raw.slice(1, -1), display: false });
    }
    cursor = index + raw.length;
  }
  if (cursor < value.length) tokens.push({ kind: "text", value: value.slice(cursor) });
  return tokens;
}

function MathToken({ value, display }: { value: string; display: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    katex.render(value, ref.current, { displayMode: display, throwOnError: false, strict: "ignore" });
    return () => ref.current?.replaceChildren();
  }, [display, value]);
  return <span ref={ref} className={display ? "mixed-math-display" : "mixed-math-inline"} aria-label="Math expression" />;
}

export function MixedContentRenderer({ text }: { text: string }) {
  const tokens = useMemo(() => tokenize(text), [text]);
  return <>{tokens.map((token, index) => {
    if (token.kind === "math") return <MathToken key={index} value={token.value} display={token.display} />;
    if (token.kind === "sup") return <sup key={index}>{token.value}</sup>;
    return <span key={index}>{token.value}</span>;
  })}</>;
}
