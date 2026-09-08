"""
디자이너 에이전트(designer_agent.py)가 만든 최종 카드뉴스 이미지(final/ +
final_manifest.json)를 대본 요약과 함께 한 페이지에서 볼 수 있는 미리보기
HTML을 만든다.

crop_images.py 단계까지의 결과를 보여주는 preview_images.py와 짝을 이루는
스크립트다 — 그쪽은 "사진이 잘 배정/크롭됐는지"를 보는 용도고, 이건 "문구까지
다 얹은 최종본이 실제로 어떻게 보이는지"를 보는 용도다. API 호출이 필요 없다
— 로컬 파일만 읽는다.

사용법
------
1. python designer_agent.py (또는 API 키 없이 빠르게 보려면
   python designer_agent.py --demo)로 final/ + final_manifest.json을 먼저 만든다.
2. python preview_final.py
3. 실행 후 생긴 final_preview.html을 Finder에서 더블클릭하거나, 터미널에서
   'open final_preview.html' 치면 기본 브라우저로 열린다.
"""

import json
from pathlib import Path


def main():
    out_dir = Path(__file__).parent
    manifest_path = out_dir / "final_manifest.json"
    if not manifest_path.exists():
        raise SystemExit(
            f"{manifest_path} 이 없습니다. 먼저 designer_agent.py를 실행하세요 "
            "(사진이 없으면 'python designer_agent.py --demo')."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    script_path = out_dir / "approved_script.json"
    script_html = ""
    if script_path.exists():
        script = json.loads(script_path.read_text(encoding="utf-8"))
        script_html = f"""
        <div class="script">
          <h2>대본 요약</h2>
          <p><b>주제</b> {script.get('topic', '')}</p>
          <p><b>표지 문구</b> {script.get('hook', '')}</p>
          <p><b>CTA</b> {script.get('cta', '')}</p>
          <p><b>댓글 유도</b> {script.get('comment_question', '')}</p>
        </div>"""

    cards_html = "".join(
        f"""
        <div class="card">
          <img src="{m['local_path']}" alt="{m['role']}">
          <div class="meta"><b>카드 {m['index']}</b> · {m['role']}</div>
        </div>"""
        for m in manifest
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>카드뉴스 최종본 미리보기</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #f5f5f5; margin: 0; padding: 24px; }}
  h1 {{ font-size: 20px; }}
  .script {{ background: white; border-radius: 12px; padding: 16px 20px; margin-bottom: 20px;
             box-shadow: 0 1px 4px rgba(0,0,0,0.15); font-size: 14px; line-height: 1.6; }}
  .script h2 {{ font-size: 15px; margin: 0 0 8px; }}
  .script p {{ margin: 4px 0; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; }}
  .card {{ background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.15); }}
  .card img {{ width: 100%; aspect-ratio: 4/5; object-fit: cover; display: block; }}
  .meta {{ padding: 10px 12px; font-size: 13px; color: #222; }}
</style>
</head>
<body>
<h1>카드뉴스 최종본 미리보기</h1>
{script_html}
<div class="grid">
{cards_html}
</div>
</body>
</html>"""

    out_path = out_dir / "final_preview.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"저장 완료: {out_path}")
    print("Finder에서 더블클릭하거나, 터미널에서 'open final_preview.html' 치면 브라우저로 열려요.")


if __name__ == "__main__":
    main()
