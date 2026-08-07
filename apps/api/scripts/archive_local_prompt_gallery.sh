#!/usr/bin/env bash
# 在确认 R2 公网封面可访问后，归档并删除本机 prompt-gallery 图片副本以腾磁盘。
# 用法（服务器上）：
#   bash /opt/aigc-studio/apps/api/scripts/archive_local_prompt_gallery.sh
set -euo pipefail

GALLERY_ROOT="${GALLERY_ROOT:-/root/prompt-gallery}"
ARCHIVE_DIR="${ARCHIVE_DIR:-/root/prompt-gallery-archive}"
KEEP_DATA="${KEEP_DATA:-1}"
SAMPLE_N="${SAMPLE_N:-12}"
R2_BASE="${R2_BASE:-https://pub-54e40727ca014de0a7fecf608f7b0412.r2.dev}"

if [[ ! -d "$GALLERY_ROOT" ]]; then
  echo "gallery not found: $GALLERY_ROOT"
  exit 0
fi

echo "== disk before =="
df -h / | tail -1
du -sh "$GALLERY_ROOT" || true

echo "== sample R2 HEAD checks =="
# Prefer known-good IDs that are already referenced by the live DB covers.
KNOWN_IDS=(15908 16882 22194 20556 17312 24126 29370 17153 14798 14657 25960 19660)
mapfile -t local_samples < <(find "$GALLERY_ROOT/images/originals" -type f -name "*.jpg" 2>/dev/null | head -n "$SAMPLE_N")
ok=0
fail=0
checked=0
for id in "${KNOWN_IDS[@]}"; do
  code=$(curl -sI -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 15 \
    -A "aigc-studio-archive-check" "$R2_BASE/images/originals/${id}.jpg" || echo 000)
  checked=$((checked + 1))
  if [[ "$code" == "200" ]]; then
    ok=$((ok + 1))
  else
    fail=$((fail + 1))
    echo "FAIL $code known:$id"
  fi
done
# A few extra random local files (best-effort; allow misses for non-imported ids)
for f in "${local_samples[@]:-}"; do
  id="$(basename "$f")"
  code=$(curl -sI -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 15 \
    -A "aigc-studio-archive-check" "$R2_BASE/images/originals/$id" || echo 000)
  checked=$((checked + 1))
  if [[ "$code" == "200" ]]; then
    ok=$((ok + 1))
  else
    fail=$((fail + 1))
    echo "MISS $code local:$id"
  fi
done
echo "sample ok=$ok fail=$fail checked=$checked"
# Require strong signal on known IDs: at least 6 known hits and known failure rate low.
if [[ "$ok" -lt 6 ]]; then
  echo "R2 sample checks failed (ok<$ok); abort delete."
  exit 2
fi
# Allow some local-only misses, but not a total outage.
if [[ "$fail" -gt $((checked / 2)) ]]; then
  echo "R2 sample checks failed (fail majority); abort delete."
  exit 2
fi

ts="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$ARCHIVE_DIR"
meta_tar="$ARCHIVE_DIR/prompt-gallery-meta-$ts.tgz"

echo "== archive metadata/scripts (keep small) =="
tar -C /root -czf "$meta_tar" \
  --exclude='prompt-gallery/images' \
  --exclude='prompt-gallery/images/*' \
  prompt-gallery || true
ls -lh "$meta_tar"

echo "== remove local image trees =="
# 只删图片目录，保留 data/ 脚本方便以后再同步
rm -rf "$GALLERY_ROOT/images"
# 历史分卷若存在也清掉
rm -f /root/prompt-gallery-part-* 2>/dev/null || true

if [[ "$KEEP_DATA" != "1" ]]; then
  rm -rf "$GALLERY_ROOT"
fi

echo "== disk after =="
df -h / | tail -1
du -sh "$GALLERY_ROOT" 2>/dev/null || true
du -sh "$ARCHIVE_DIR" 2>/dev/null || true
echo "done. metadata archive: $meta_tar"
