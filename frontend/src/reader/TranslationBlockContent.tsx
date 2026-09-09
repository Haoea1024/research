import type { Block, Figure } from "../api/types";
import { useTranslationStore } from "../stores/translationStore";
import { FigureInFlow } from "./FigureInFlow";
import { FormulaBlock } from "./FormulaBlock";
import { MixedContentRenderer } from "./MixedContentRenderer";
import { TableInFlow } from "./TableInFlow";

interface Props { block: Block; figure?: Figure; layout?: boolean; showSourceDetails?: boolean; onRetranslate?: (blockId: string) => void; }

export function TranslationBlockContent({ block, figure, layout = false, showSourceDetails = false, onRetranslate }: Props) {
  const translation = useTranslationStore((state) => state.byBlockId[block.id]);
  if (block.type === "formula") return <FormulaBlock source={block.content_md} />;
  if (layout && block.type === "figure") return <FigureInFlow figure={figure} />;
  if (layout && block.type === "table") return <TableInFlow table={figure} />;
  const source = block.type === "table"
    ? figure?.caption_text || "[Table content available in parser data]"
    : block.content_md?.trim() || (layout ? "" : "[No textual content]");
  const showTranslation = block.is_translatable && Boolean(translation?.zh_text);
  const status = block.is_translatable ? (translation?.status ?? "pending") : null;
  const inProgress = status === "queued" || status === "translating";
  const canRetry = status === "failed" || Boolean(translation?.retranslate_failed);
  const skipNotice = translation?.skip_reason === "MALFORMED_FRAGMENT"
    ? "解析片段不完整，已跳过翻译"
    : translation?.skip_reason === "REFERENCE_LIST"
      ? "参考文献列表，已跳过翻译"
      : null;
  return (
    <>
      {status ? <span className={`translation-state state-${status}`} aria-label={`Translation ${status}`}>{status}</span> : null}
      {!layout && (block.type === "figure" || block.type === "table") ? <div className="media-placeholder" data-testid={`${block.type}-placeholder`}><strong>{block.type === "table" ? "Table" : "Figure"} parser content</strong><small>Open Layout view to see the original crop in reading flow.</small></div> : null}
      <div className={`block-content ${showTranslation ? "translated-content" : "english-fallback"} ${inProgress ? "is-translating" : ""}`}><MixedContentRenderer text={(showTranslation ? translation?.zh_text : source) ?? ""} /></div>
      {showSourceDetails && showTranslation ? <details className="source-fallback"><summary>查看英文原文</summary><MixedContentRenderer text={source} /></details> : null}
      {inProgress ? <span className="translation-progress-hint">翻译中，暂时显示英文</span> : null}
      {status === "failed" || translation?.retranslate_failed ? <div className="translation-error">{translation?.retranslate_failed ? "重译失败，已保留上次成功译文" : translation?.error}</div> : null}
      {status === "skipped" && showSourceDetails ? <div className="translation-skip">已跳过：{translation?.skip_reason}</div> : null}
      {status === "skipped" && skipNotice ? <div className="translation-skip parser-warning">{skipNotice}</div> : null}
      {block.is_translatable && canRetry ? <button className="retry-button" onClick={() => onRetranslate?.(block.id)}>重试翻译</button> : null}
    </>
  );
}
