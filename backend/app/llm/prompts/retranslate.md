The previous Chinese translation failed the language-drift check. Translate this
single target block again into academic Chinese.

Paper title: {{ paper_title }}
Measured Chinese ratio: {{ chinese_ratio }}
Rejected output: {{ rejected_text }}

Glossary entries:
{{ glossary_json }}

Context and target blocks are JSON. Return only the block with context_only=false.
Return JSON only:
{"translations":[{"block_id":"...","zh_text":"..."}]}

Blocks:
{{ blocks_json }}
