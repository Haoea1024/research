import katex from "katex";
import "katex/dist/katex.min.css";

export function FormulaBlock({ source }: { source: string | null }) {
  const formula = (source ?? "").trim().replace(/^\$\$\s*/, "").replace(/\s*\$\$$/, "");
  return (
    <div className="formula-content" aria-label="Formula" dangerouslySetInnerHTML={{
      __html: katex.renderToString(formula, { displayMode: true, throwOnError: false, strict: "ignore" }),
    }} />
  );
}
