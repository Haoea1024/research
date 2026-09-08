Translate only the target blocks into accurate academic Chinese.

Paper title: {{ paper_title }}

Glossary entries that occur in this local window:
{{ glossary_json }}

Local blocks are JSON. Blocks with context_only=true are context only and MUST NOT
appear in the output. Return every target block exactly once, with no extra IDs.

Return JSON only, exactly in this shape:
{"translations":[{"block_id":"...","zh_text":"..."}]}

Preserve technical meaning, citations, numbers, symbols, and proper names. Use the
provided glossary consistently. Do not return blank translations or Markdown fences.

Local blocks:
{{ blocks_json }}
