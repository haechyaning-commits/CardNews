"""
크롭까지 끝난 최종 이미지(crop_manifest.json + images/ 폴더)를 한 페이지에서
볼 수 있는 미리보기 HTML을 만든다. crop_manifest.json이 없으면
photo_assignments.json(크롭 전, Unsplash 원본 URL)으로 대신 보여준다.

API 호출이 필요 없다 — 로컬 파일만 읽는다.

사용법: python preview_images.py
실행 후 생긴 preview.html을 Finder에서 더블클릭하거나, 터미널에서
'open preview.html' 치면 기본 브라우저로 열린다.
"""

import json
from pathlib import Path


def build_card_html(a: dict, use_local: bool) -> str:
    img = a.get("image")
    if img is None:
        return f"""
        <div class="card">
          <div class="no-image">이미지 없음</div>
          <div class="meta"><b>카드 {a['index']} ({a['role']})</b><br>{a['text']}</div>
        </div>"""

    if use_local and a.get("local_path"):
        src = a["local_path"]
        size_badge = "✅ 1080x1350 (최종 크기)"
    else:
        src = img["url_regular"]
        ratio_ok = img.get("close_to_4_5")
        size_badge = "✅ 4:5에 가까움 (크롭 전 원본)" if ratio_ok else "⚠️ 크롭 전 원본 (4:5와 차이 있음)"

    likes = img.get("likes")
    likes_note = f" (좋아요 {likes}개)" if likes is not None else ""

    return f"""
    <div class="card">
      <img src="{src}" alt="{img.get('alt_description', '')}">
      <div class="meta">
        <b>카드 {a['index']} ({a['role']})</b><br>
        {a['text']}<br>
        <span class="badge">{size_badge}</span><br>
        <span class="credit">📷 {img['photographer']} on {img.get('source_label', 'Unsplash')}{likes_note}</span><br>
        <span class="reason">선택 이유: {img['reason']}</span>
      </div>
    </div>"""


def main():
    out_dir = Path(__file__).parent
    manifest_path = out_dir / "crop_manifest.json"
    assignments_path = out_dir / "photo_assignments.json"

    if manifest_path.exists():
        data_path = manifest_path
        use_local = True
    elif assignments_path.exists():
        data_path = assignments_path
        use_local = False
        print("crop_manifest.json이 없어서 크롭 전 원본(photo_assignments.json)으로 보여줘요. "
              "정확한 최종 이미지를 보려면 crop_images.py를 먼저 실행하세요.")
    else:
        raise SystemExit("photo_assignments.json도 crop_manifest.json도 없습니다. photo_agent.py부터 실행하세요.")

    assignments = json.loads(data_path.read_text(encoding="utf-8"))
    cards_html = "".join(build_card_html(a, use_local) for a in assignments)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>카드뉴스 이미지 미리보기</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #f5f5f5; margin: 0; padding: 24px; }}
  h1 {{ font-size: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; }}
  .card {{ background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.15); }}
  .card img {{ width: 100%; aspect-ratio: 4/5; object-fit: cover; display: block; }}
  .no-image {{ aspect-ratio: 4/5; display:flex; align-items:center; justify-content:center; background:#eee; color:#999; }}
  .meta {{ padding: 10px 12px; font-size: 13px; line-height: 1.5; color: #222; }}
  .badge {{ display:inline-block; margin-top:4px; font-size:12px; color:#555; }}
  .credit {{ display:block; margin-top:4px; font-size:12px; color:#777; }}
  .reason {{ display:block; margin-top:4px; font-size:12px; color:#999; }}
</style>
</head>
<body>
<h1>카드뉴스 이미지 미리보기</h1>
<div class="grid">
{cards_html}
</div>
</body>
</html>"""

    out_path = out_dir / "preview.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"저장 완료: {out_path}")
    print("Finder에서 더블클릭하거나, 터미널에서 'open preview.html' 치면 브라우저로 열려요.")


if __name__ == "__main__":
    main()
