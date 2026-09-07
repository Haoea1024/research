# S0 MinerU parsing spike

This spike validates MinerU's real output shape before product code or a database is built.

## Local environment used

- Conda environment: `paper-agent` (Python 3.11.16)
- MinerU: 3.4.5, `pipeline` backend on CPU
- Sample: *Deep Residual Learning for Image Recognition* (arXiv:1512.03385)

The sample PDF, MinerU output, logs, rendered page images, and generated viewer HTML are local artifacts and are intentionally ignored by Git.

## Reproduce

```powershell
conda activate paper-agent

mineru -p spike/papers/resnet_1512.03385.pdf -o spike/out -b pipeline

python spike/parse_bench.py `
  spike/out/resnet_1512.03385/auto/resnet_1512.03385_content_list.json

python spike/bbox_viewer/generate_viewer.py `
  --pdf spike/papers/resnet_1512.03385.pdf `
  --content spike/out/resnet_1512.03385/auto/resnet_1512.03385_content_list.json `
  --out spike/bbox_viewer
```

Open `spike/bbox_viewer/index.html` after generation. The viewer is static and needs no application server.

## Verified result

- 12 pages and 177 ordered blocks
- 3 images, 9 charts, 15 tables, and 20 captioned blocks
- Every block has a valid `page_idx`, `type`, and ordered four-number `bbox`
- Viewer generated 12 page images and exposes page navigation, block-type filters, `order_idx`, figures, tables, and captions

`qwen_compare.py` is only a deferred integration boundary. It returns a non-zero `BLOCKED` result and makes no external request.
