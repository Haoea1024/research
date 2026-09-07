#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MinerU bbox 可视化生成器（S0 spike 调试工具）。

读取 MinerU pipeline 输出的 content_list.json + 原始 PDF：
  1. 用 pypdfium2 把每页渲染成 PNG（pages/page_000.png ...）
  2. 读取 content_list.json，把每个 block 拍平成展示记录
  3. 生成一个自包含的 index.html，叠加显示：
     - 页面（逐页渲染 + 页码导航）
     - bbox（归一化 0-1000 → 按图像尺寸映射成像素框）
     - block 类型（type，按类型着色；text_level==1 视作 title）
     - order_idx（阅读顺序 = content_list 扁平列表下标）
     - figure / table（image/chart/table 块高亮 + 特殊标识）
     - caption（image_caption / table_caption / chart_caption）

用法：
    python generate_viewer.py \
        --pdf spike/out/<paper>/auto/<paper>_origin.pdf \
        --content spike/out/<paper>/auto/<paper>_content_list.json \
        --out spike/bbox_viewer
"""
import argparse
import html
import json
import sys
from pathlib import Path

import pypdfium2 as pdfium

# 块类型 → 颜色（title 是 text_level==1 的 text 块的展示类别）
COLORS = {
    "title": "#7b1fa2",
    "text": "#1565c0",
    "equation": "#ef6c00",
    "image": "#2e7d32",
    "chart": "#00838f",
    "table": "#c62828",
    "list": "#6d4c41",
    "aside_text": "#78909c",
    "page_footnote": "#9e9e9e",
    "page_number": "#bdbdbd",
}


def render_pages(pdf_path: Path, pages_dir: Path, scale: float = 2.0) -> int:
    """渲染 PDF 每页为 PNG，返回页数。"""
    pages_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    n = len(pdf)
    for i in range(n):
        page = pdf[i]
        bitmap = page.render(scale=scale)
        pil = bitmap.to_pil()
        pil.save(pages_dir / f"page_{i:03d}.png")
        bitmap.close()
        page.close()
    pdf.close()
    return n


def flatten_blocks(content_list: list) -> list:
    """把 content_list 块拍平成前端易用的记录，order_idx = 列表下标。"""
    out = []
    for idx, b in enumerate(content_list):
        t = b.get("type")
        level = b.get("text_level")
        kind = "title" if (t == "text" and level == 1) else t
        rec = {
            "order_idx": idx,
            "type": t,
            "kind": kind,
            "level": level,
            "page_idx": b.get("page_idx"),
            "bbox": b.get("bbox"),
            "text": b.get("text"),
            "captions": [],
            "img_path": b.get("img_path"),
            "table_body": b.get("table_body"),
        }
        for cap_key in ("image_caption", "table_caption", "chart_caption"):
            caps = b.get(cap_key) or []
            if caps:
                rec["captions"].extend(caps)
        if t == "list":
            rec["list_items"] = b.get("list_items") or []
        out.append(rec)
    return out


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MinerU bbox viewer — __PAPER_HTML__</title>
<style>
  :root { --bar-h: 48px; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; background:#f4f5f7; color:#222; }
  header {
    position: sticky; top:0; z-index: 50; background:#fff; border-bottom:1px solid #e0e0e0;
    padding: 8px 16px; display:flex; flex-wrap:wrap; gap:12px; align-items:center;
  }
  header h1 { font-size:15px; margin:0; white-space:nowrap; }
  .legend { display:flex; flex-wrap:wrap; gap:6px 12px; align-items:center; font-size:12px; }
  .legend label { display:flex; align-items:center; gap:4px; cursor:pointer; user-select:none; }
  .swatch { width:11px; height:11px; border-radius:2px; display:inline-block; }
  .pagenav { display:flex; gap:4px; align-items:center; flex-wrap:wrap; }
  .pagenav a { text-decoration:none; color:#1565c0; font-size:12px; padding:2px 7px; border:1px solid #cfd8dc; border-radius:4px; background:#fff; }
  .pagenav a:hover { background:#e3f2fd; }
  main { padding: 16px; display:flex; gap:16px; align-items:flex-start; }
  #pages { flex:1; display:flex; flex-direction:column; gap:24px; min-width:0; }
  .page { background:#fff; border:1px solid #e0e0e0; border-radius:6px; padding:10px; box-shadow:0 1px 3px rgba(0,0,0,.08); }
  .page h2 { font-size:13px; margin:0 0 8px; color:#555; }
  .page-inner { position:relative; display:inline-block; line-height:0; }
  .page-inner img { display:block; }
  .overlay { position:absolute; inset:0; pointer-events:none; }
  .bbox { position:absolute; border:2px solid #999; pointer-events:auto; cursor:pointer; }
  .bbox:hover { z-index:10; filter:brightness(1.15); }
  .bbox .tag {
    position:absolute; top:-1px; left:-1px; transform:translateY(-100%);
    font-size:10px; line-height:1; white-space:nowrap; padding:2px 4px; color:#fff;
    background:inherit; border-radius:2px 2px 0 0; border:1px solid rgba(0,0,0,.15);
  }
  .bbox .cap-badge { position:absolute; top:2px; right:2px; font-size:11px; }
  .bbox.flash { outline:4px solid #ffd600; }
  #index { width: 340px; max-height: calc(100vh - 80px); position:sticky; top:64px; overflow:auto;
    background:#fff; border:1px solid #e0e0e0; border-radius:6px; padding:8px; flex-shrink:0; }
  #index h2 { font-size:13px; margin:0 0 8px; color:#555; }
  #index .item { display:flex; gap:6px; align-items:baseline; font-size:12px; padding:3px 4px; cursor:pointer; border-radius:3px; }
  #index .item:hover { background:#f0f4ff; }
  #index .idx { color:#999; min-width:34px; text-align:right; font-variant-numeric:tabular-nums; }
  #index .kind { min-width:70px; }
  #index .snippet { color:#666; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  #tooltip {
    position:fixed; z-index:200; display:none; max-width:520px; max-height:360px; overflow:auto;
    background:#1e1e1e; color:#eee; font-size:12px; padding:10px 12px; border-radius:6px;
    box-shadow:0 4px 16px rgba(0,0,0,.4); pointer-events:none; word-break:break-word;
  }
  #tooltip .cap { color:#ffd54f; }
  #tooltip .tbl { color:#90caf9; }
  #tooltip pre { white-space:pre-wrap; margin:4px 0 0; }
</style>
</head>
<body>
<header>
  <h1>📄 __PAPER_HTML__</h1>
  <div class="legend" id="legend"></div>
  <div class="pagenav" id="pagenav"></div>
</header>
<main>
  <div id="pages"></div>
  <aside id="index"><h2>块索引（order_idx / 类型 / 页码）</h2><div id="index-list"></div></aside>
</main>
<div id="tooltip"></div>

<script>
const COLORS = __COLORS__;
const PAPER = __PAPER_JSON__;
const NUM_PAGES = __NPAGES__;
const BLOCKS = __BLOCKS__;

const KIND_LABEL = {
  title:"标题", text:"正文", equation:"公式", image:"图(figure)", chart:"图(chart)",
  table:"表格", list:"列表", aside_text:"边栏", page_footnote:"脚注", page_number:"页码"
};

const hidden = new Set();   // 被勾掉的 kind

function esc(s){ return (s==null?"":String(s)).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// ---- 图例 + 过滤 ----
function buildLegend(){
  const kinds = [...new Set(BLOCKS.map(b => b.kind))];
  const lg = document.getElementById('legend');
  kinds.forEach(k => {
    const label = document.createElement('label');
    const sw = document.createElement('span'); sw.className='swatch';
    sw.style.background = COLORS[k] || '#999';
    const cb = document.createElement('input'); cb.type='checkbox'; cb.checked = true;
    const n = BLOCKS.filter(b=>b.kind===k).length;
    cb.addEventListener('change', () => { cb.checked ? hidden.delete(k) : hidden.add(k); applyFilters(); });
    const txt = document.createElement('span'); txt.textContent = `${KIND_LABEL[k]||k}(${n})`;
    label.append(cb, sw, txt);
    lg.appendChild(label);
  });
}
function applyFilters(){
  document.querySelectorAll('.bbox').forEach(el => {
    el.style.display = hidden.has(el.dataset.kind) ? 'none' : '';
  });
}

// ---- 页码导航 ----
function buildPagenav(){
  const nav = document.getElementById('pagenav');
  for(let i=0;i<NUM_PAGES;i++){
    const a = document.createElement('a');
    a.href = '#page-'+i; a.textContent = 'p'+(i+1);
    nav.appendChild(a);
  }
}

// ---- 渲染页面 ----
function buildPages(){
  const wrap = document.getElementById('pages');
  for(let i=0;i<NUM_PAGES;i++){
    const sec = document.createElement('div');
    sec.className='page'; sec.id = 'page-'+i;
    const h = document.createElement('h2'); h.textContent = '第 '+(i+1)+' 页';
    const inner = document.createElement('div'); inner.className='page-inner';
    const img = document.createElement('img'); img.src = 'pages/page_'+String(i).padStart(3,'0')+'.png';
    const ov = document.createElement('div'); ov.className='overlay'; ov.dataset.page = i;
    inner.append(img, ov);
    sec.append(h, inner);
    wrap.appendChild(sec);
    img.addEventListener('load', () => renderOverlay(ov, img));
  }
}
function renderOverlay(overlay, img){
  const pid = +overlay.dataset.page;
  const W = img.naturalWidth, H = img.naturalHeight;
  BLOCKS.filter(b => b.page_idx === pid).forEach(b => {
    const [x0,y0,x1,y1] = b.bbox;
    const d = document.createElement('div');
    d.className = 'bbox';
    d.dataset.kind = b.kind; d.dataset.idx = b.order_idx;
    const color = COLORS[b.kind] || '#999';
    d.style.borderColor = color;
    d.style.left   = (x0/1000*W)+'px';
    d.style.top    = (y0/1000*H)+'px';
    d.style.width  = ((x1-x0)/1000*W)+'px';
    d.style.height = ((y1-y0)/1000*H)+'px';
    const tag = document.createElement('span'); tag.className='tag';
    tag.style.background = color;
    tag.textContent = '#'+b.order_idx+' '+(KIND_LABEL[b.kind]||b.kind)+(b.level?' L'+b.level:'');
    d.appendChild(tag);
    if(b.captions && b.captions.length){
      const cap = document.createElement('span'); cap.className='cap-badge'; cap.textContent='📄'; cap.title='有 caption';
      d.appendChild(cap);
    }
    d.addEventListener('mouseenter', e => showTip(b,e));
    d.addEventListener('mouseleave', hideTip);
    d.addEventListener('click', () => { d.classList.add('flash'); setTimeout(()=>d.classList.remove('flash'), 800); });
    overlay.appendChild(d);
  });
}

// ---- 悬浮提示 ----
const tip = document.getElementById('tooltip');
function showTip(b, e){
  let html = '<b>#'+b.order_idx+'</b> &nbsp;['+(KIND_LABEL[b.kind]||b.kind)+']'+(b.level?' <span style="color:#aaa">L'+b.level+'</span>':'')+' &nbsp;<span style="color:#aaa">p'+(b.page_idx+1)+'</span>';
  if(b.bbox) html += '<br><span style="color:#aaa">bbox '+JSON.stringify(b.bbox)+'</span>';
  if(b.captions && b.captions.length) html += '<br><span class="cap">📄 '+b.captions.map(esc).join('</span><br><span class="cap">📄 ')+'</span>';
  if(b.text) html += '<pre>'+esc(b.text)+'</pre>';
  if(b.list_items && b.list_items.length) html += '<pre>'+esc(b.list_items.join('\n'))+'</pre>';
  if(b.img_path) html += '<br><span style="color:#aaa">'+esc(b.img_path)+'</span>';
  if(b.table_body) html += '<br><span class="tbl">HTML table:</span><pre>'+esc(b.table_body)+'</pre>';
  tip.innerHTML = html; tip.style.display='block';
  const m = 14;
  let x = e.clientX + m, y = e.clientY + m;
  const r = tip.getBoundingClientRect();
  if(x + r.width > window.innerWidth) x = e.clientX - m - r.width;
  if(y + r.height > window.innerHeight) y = e.clientY - m - r.height;
  tip.style.left = x+'px'; tip.style.top = y+'px';
}
function hideTip(){ tip.style.display='none'; }

// ---- 块索引侧栏 ----
function buildIndex(){
  const list = document.getElementById('index-list');
  BLOCKS.forEach(b => {
    const item = document.createElement('div'); item.className='item';
    const idx = document.createElement('span'); idx.className='idx'; idx.textContent = '#'+b.order_idx;
    const sw = document.createElement('span'); sw.className='swatch'; sw.style.background = COLORS[b.kind]||'#999';
    const kind = document.createElement('span'); kind.className='kind'; kind.textContent = KIND_LABEL[b.kind]||b.kind;
    const pg = document.createElement('span'); pg.className='snippet'; pg.style.color='#aaa'; pg.textContent='p'+(b.page_idx+1);
    const snip = document.createElement('span'); snip.className='snippet';
    snip.textContent = (b.text || (b.captions&&b.captions[0]) || b.img_path || '').replace(/\s+/g,' ').slice(0,40);
    item.append(idx, sw, kind, pg, snip);
    item.addEventListener('click', () => {
      document.getElementById('page-'+b.page_idx).scrollIntoView({behavior:'smooth', block:'start'});
      const el = document.querySelector(`.bbox[data-idx="${b.order_idx}"]`);
      if(el){ el.classList.add('flash'); setTimeout(()=>el.classList.remove('flash'), 1200); }
    });
    list.appendChild(item);
  });
}

buildLegend(); buildPagenav(); buildPages(); buildIndex();
</script>
</body>
</html>
"""


def build_html(paper_name: str, n_pages: int, blocks: list) -> str:
    def json_for_script(value: object) -> str:
        return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")

    rendered = HTML_TEMPLATE
    rendered = rendered.replace("__PAPER_HTML__", html.escape(paper_name))
    rendered = rendered.replace("__PAPER_JSON__", json_for_script(paper_name))
    rendered = rendered.replace("__NPAGES__", str(n_pages))
    rendered = rendered.replace("__COLORS__", json_for_script(COLORS))
    rendered = rendered.replace("__BLOCKS__", json_for_script(blocks))
    return rendered


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 MinerU bbox 可视化页面")
    ap.add_argument("--pdf", required=True, help="原始 PDF 路径（渲染用）")
    ap.add_argument("--content", required=True, help="content_list.json 路径")
    ap.add_argument("--out", required=True, help="输出目录（写入 index.html + pages/）")
    ap.add_argument("--scale", type=float, default=2.0, help="渲染缩放（默认 2.0 ≈ 144dpi）")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    content_path = Path(args.content)
    out_dir = Path(args.out)
    if not pdf_path.exists():
        print(f"[错误] PDF 不存在: {pdf_path}", file=sys.stderr)
        return 1
    if not content_path.exists():
        print(f"[错误] content_list.json 不存在: {content_path}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = out_dir / "pages"

    print(f"[1/3] 渲染 PDF 页面 -> {pages_dir}")
    n_pages = render_pages(pdf_path, pages_dir, scale=args.scale)
    print(f"      页数: {n_pages}")

    print(f"[2/3] 读取 content_list -> {content_path}")
    content_list = json.loads(content_path.read_text(encoding="utf-8"))
    blocks = flatten_blocks(content_list)
    print(f"      块数: {len(blocks)}")

    print(f"[3/3] 生成 index.html -> {out_dir / 'index.html'}")
    paper_name = pdf_path.stem
    html = build_html(paper_name, n_pages, blocks)
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    print("完成。用浏览器打开:", out_dir / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
