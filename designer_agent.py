"""
디자이너(Designer) 에이전트

crop_images.py가 만들어둔 로컬 이미지(crop_manifest.json + images/, 이미 1080x1350
4:5로 크롭되고 톤 보정까지 끝난 상태)에 작가가 쓴 문구를 얹어서 실제 인스타그램에
올릴 최종 카드뉴스 PNG를 만든다. Skill 문서 3번(디자이너 규칙)을 코드로 강제한다:

- 전체 슬라이드 4:5(1080x1350) 고정 — crop_images.py가 이미 보장하므로 여기선 그대로 사용.
- 템플릿 3종 고정: 헤더(표지) / 본문(슬라이드) / 마무리(CTA+댓글유도+핸들).
- 폰트 최대 2종(제목 1개 + 본문 1개, 굵기로 위계). 색상은 흰 텍스트 / 포인트색 /
  요약제목·포인트 박스(흰 배경 또는 짙은 반투명 배경) 3가지로 고정.
- 사진 위에 바로 얹는 텍스트(표지 제목/킥커, 본문 문단, 마무리 CTA/질문/핸들)는
  어두운 글자 외곽선(stroke)으로 가독성을 확보한다 — "글씨 뒤에 검은 배경이
  깔리는 게 이상하다"는 피드백으로 사진을 어둡게 덮던 스크림(반투명
  그라데이션/오버레이)을 걷어내고, 사진은 그대로 보이게 하되 외곽선만으로
  밝은 사진 위에서도 흰 글자가 묻히지 않게 했다(draw_wrapped의
  stroke_width/stroke_fill). 요약제목/포인트는 원래부터 스크림이 아니라 자체
  불투명 박스를 쓰고 있어서 이 변경과 무관하게 그대로다.
- 상하 15%는 프로필 아이콘/캡션 UI에 가려질 수 있는 세이프존이라 핵심 텍스트는
  그 안쪽에 배치한다.

레이아웃(v4): 아래 피드백을 반영해서 여러 차례 고쳤다.
- "문장이 중간에 끊겨 보인다", "카드마다 위치가 달라 산만하다" → 모든 본문
  카드가 항상 같은 골격(하단 고정 본문 + 필요하면 그 위에 요약 제목/포인트)을
  쓰되, 골격 안의 요소 구성은 카드 내용에 따라 달라지게 함.
- "표지/배경설명/핵심정보 같은 라벨은 본문 내용이 아니니 없애라" → 역할 태그
  자체를 삭제. 카드엔 이제 실제 콘텐츠만 보인다.
- "표지 제목이 hook 문장 그대로라 너무 길다, 딱 제목처럼 짧고 흥미롭게" →
  Claude가 hook을 그대로 안 쓰고 짧고 강렬한 표지 제목(cover_title)을 새로
  뽑아서 씀.
- "박스는 검정 대신 흰색으로, 둥근 모서리 대신 각지게, 항상 넣을 필요는 없이
  이미지랑 대본을 보고 디자인" → 요약 제목/포인트 박스를 흰 배경+검정 각진
  테두리 스타일로 바꾸고(render_box_text), 카드 사진을 실제로 같이 보여주면서
  Claude가 "이 카드에 필요한가"를 판단하게 해서(annotate_cards가 vision 입력을
  받음) 필요 없으면 박스 자체를 안 그림.
- "핵심 볼드체가 안 됐다" → 안전장치(강조 표시를 지운 본문이 원문과 다르면
  강조를 포기하고 원문 그대로 쓰는 로직)가 공백 하나 차이에도 걸려서 강조가
  자주 빠졌던 걸 확인 — 공백 차이는 무시하는 느슨한 비교로 완화하고, 폴백이
  발생하면 콘솔에 로그를 남기게 함.
- 전부 왼쪽 정렬로 통일해서(참고 레퍼런스 스타일) 카드마다 다른 배치가 아니라
  "같은 시스템, 다른 내용"으로 일관성을 줌.
- "표지에 임팩트가 없다, 디자인이 단조롭다, 박스 색/위치를 사진에 맞게
  유연하게, 디자이너로서 판단해라" → 표지 제목을 글자 수에 따라 동적으로
  키우고(_title_font_size) 사진 구도에 맞춰 3가지 배치(하단좌측/가운데/
  상단좌측) 중 하나를 씀. 본문 카드의 요약 제목/포인트 박스도 흰색 하나로
  고정하지 않고 light/dark 두 배색과 좌/우 위치 중 Claude가 그 카드 사진을
  보고 고르게 함(BOX_STYLES, box_style/align) — 매 카드가 똑같은 자리에
  똑같은 색으로만 나오지 않도록.

이 표지 제목/정렬, 요약 제목/포인트와 그 배색·위치, 강조 구간은 문장을 새로
쓰는 게 아니라 "무엇이 필요한지·어디에 어떻게 놓을지"를 판단하는 작업이라
Claude 호출이 필요하다(annotate_cards, 카드 사진도 같이 보냄). ANTHROPIC_API_KEY가
없으면 이 단계를 건너뛰고 표지는 hook 원문을 기본 배치로, 본문 카드는 요약
제목/강조/포인트 없이 기본 스타일(흰 박스/왼쪽)로만 렌더링한다 — API 키가
없어도 파이프라인 자체는 죽지 않는다.

approved_script.json에는 슬라이드(표지+2~8번)와 별개로 cta/comment_question이
최상위 필드로 따로 있다(어느 슬라이드에도 안 묶여 있음) — 이건 "마무리" 카드가
아직 없어서다. 그래서 여기서 마지막 슬라이드 이미지를 재사용한 "마무리" 카드를
하나 더 만들어서 cta+comment_question+계정 핸들을 얹는다. 이렇게 하면 슬라이드
총 장수(원래 8장 + 마무리 1장 = 9장)도 Skill의 "7~10장" 범위 안에 그대로 들어간다.

폰트: 한글이 보이는 TTF/OTF가 필요하다. 아래 순서로 자동 탐색한다.
1. FONT_REGULAR_PATH / FONT_BOLD_PATH 환경변수로 직접 지정한 경로
2. 프로젝트 폴더의 fonts/NotoSansKR-Regular.otf / fonts/NotoSansKR-Bold.otf
   (무료 다운로드: https://fonts.google.com/noto/specimen/Noto+Sans+KR)
3. macOS/Windows/Linux에 흔히 이미 깔려있는 한글 폰트(맑은 고딕, Apple SD 산돌고딕,
   나눔고딕, Noto Sans CJK 등)
아무것도 못 찾으면 실행을 멈추고 fonts/ 폴더에 폰트를 넣으라고 안내한다.

사용법
------
1. pip install Pillow anthropic requests
2. crop_manifest.json + images/ 가 폴더에 있어야 한다 (먼저 crop_images.py 실행).
   Unsplash/Pexels API 키 없이 레이아웃만 빠르게 보고 싶으면 이 단계를
   건너뛰고 3번 대신 `python designer_agent.py --demo`로 실행해도 된다 —
   approved_script.json의 예시 문구는 그대로 쓰고 사진 자리만 단색으로
   채운다.
3. export ANTHROPIC_API_KEY="..." — 카드별 요약 제목/강조/포인트를 만드는 데 씀.
   없어도 실행은 되지만 그 세 가지 없이 기본 스타일로만 렌더링된다.
4. (필요하면) export ACCOUNT_HANDLE="@계정핸들" — 마무리 카드 하단에 표시된다.
   안 정하면 "@계정핸들"이 자리표시자로 들어가니 실제 발행 전에 바꿔야 한다.
5. python designer_agent.py   (또는 python designer_agent.py --demo)
   (같은 폴더의 review_log.json이 "미승인(max_revisions_reached)"으로 남아있으면
   안전장치가 실행을 막는다 — 그래도 진행하려면 --force를 같이 붙인다)
6. python preview_final.py 를 실행하면 final/ 안의 카드 9장을 한 페이지로
   모아 보여주는 final_preview.html이 생긴다 — 'open final_preview.html'로
   브라우저에서 확인.

결과: final/ 폴더에 card_01_표지.png ~ card_09_마무리.png 로 저장되고,
각 카드의 최종 경로/역할이 담긴 final_manifest.json도 같이 생성된다.
"""

import base64
import colorsys
import io
import json
import os
import re
import sys
from pathlib import Path

import anthropic
from PIL import Image, ImageDraw, ImageFont

PROJECT_DIR = Path(__file__).parent
MODEL = "claude-sonnet-5"

CANVAS_W, CANVAS_H = 1080, 1350

# 상하 15%는 인스타 UI(프로필 아이콘, 캡션 등)에 가려질 수 있는 세이프존.
# 핵심 텍스트는 이 안쪽(SAFE_TOP ~ SAFE_BOTTOM)에만 배치한다.
SAFE_TOP = int(CANVAS_H * 0.15)
SAFE_BOTTOM = CANVAS_H - int(CANVAS_H * 0.15)
CONTENT_MARGIN_X = 72  # 좌우 여백(왼쪽 정렬 기준선)
CONTENT_WIDTH = CANVAS_W - CONTENT_MARGIN_X * 2

# 세이프존 맨 위에서 첫 요소(요약 제목 등)가 시작하기 전 여백. 예전엔 역할
# 태그(표지/배경설명/핵심정보 같은 라벨)가 이 자리를 차지했는데, "본문 내용이
# 아닌 라벨이 카드에 들어가는 게 이상하다"는 피드백을 받고 태그 자체를 없앴다.
CONTENT_TOP_PAD = 16

# 색상 팔레트. 사진 위에 바로 얹는 텍스트(어두운 외곽선으로 가독성 확보)는
# 흰 텍스트 / 포인트색을 고정으로 쓴다. 요약 제목/포인트 박스는 light(흰
# 배경+짙은 텍스트) / dark(짙은 반투명 배경+흰 텍스트) 두 버전이 있지만,
# 카드마다 따로 고르지 않고 카드
# 세트 전체에 "딱 하나"만 정해서 통일한다(build_cards에서) — 사진수집가가
# 세트 톤을 한 번만 정하는 것과 같은 원리. 카드마다 흰 박스/검정 박스가
# 섞이면 오히려 산만하고 통일감이 없어 보인다는 피드백을 받았다.
COLOR_TEXT = (255, 255, 255, 255)
COLOR_ACCENT = (232, 176, 132, 255)
# 순검정에 가까우면 사진 위에서 "이질적인 검은 박스"처럼 붕 떠 보인다는
# 피드백을 받고, 계정 고유 웜톤과 어울리게 붉은기를 더 살린 짙은 브라운으로
# 조정했다(예전 (20,15,12) → 지금 (36,22,17)).
COLOR_SCRIM = (36, 22, 17)
# "글씨 뒤에 검은 배경이 깔리는 게 이상하다"는 피드백으로 스크림(사진을 어둡게
# 깔던 반투명 그라데이션/오버레이)을 없앤 자리에, 사진 위에 바로 얹는 텍스트
# (표지 제목/킥커, 본문 문단, 마무리 CTA/질문/핸들)의 가독성을 대신 지켜주는
# 글자 외곽선 색. 순검정 대신 COLOR_SCRIM과 같은 웜톤 브라운을 써서 스크림을
# 없앤 것과 같은 색 언어를 유지한다.
COLOR_STROKE = (*COLOR_SCRIM, 255)

# light 버전: 밝은 사진 위에서도 항상 또렷한 흰 박스+짙은 텍스트(참고
# 레퍼런스 스타일). dark 버전: 사진이 이미 밝고 화사해서 흰 박스를 얹으면
# 튀거나 밋밋해 보일 때, 사진 톤에 자연스럽게 녹아드는 짙은 반투명 박스+흰
# 텍스트. 테두리 선 없이 배경색만 채운다 — 선으로 둘러싸이는 느낌이 싫다는
# 피드백을 받고 뺐다.
BOX_STYLES = {
    "light": {"bg": (255, 255, 255, 235), "text": (24, 20, 18, 255), "point_text": (168, 88, 40, 255)},
    "dark": {"bg": (*COLOR_SCRIM, 210), "text": (255, 255, 255, 255), "point_text": (232, 176, 132, 255)},
}

TITLE_SIZE = 72    # 표지 hook / 마무리 CTA
HEADING_SIZE = 54  # 본문 카드 상단 요약 제목
BODY_SIZE = 48     # 슬라이드 본문
POINT_SIZE = 36    # 포인트 칩
LABEL_SIZE = 30    # 역할 태그 / 페이지 인디케이터 / 계정 핸들

ACCOUNT_HANDLE = os.environ.get("ACCOUNT_HANDLE", "@계정핸들")


# ---------------------------------------------------------------------------
# 폰트 탐색
# ---------------------------------------------------------------------------

# (경로, ttc 안에서 몇 번째 폰트인지) 순서로 후보를 둔다. 앞에 있을수록 우선.
# 프로젝트 fonts/ 폴더는 index가 필요 없는 단일 폰트 파일(otf/ttf)이라 0으로 둔다.
_REGULAR_CANDIDATES = [
    (PROJECT_DIR / "fonts" / "NotoSansKR-Regular.otf", 0),
    (PROJECT_DIR / "fonts" / "NotoSansKR-Regular.ttf", 0),
    (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), 2),  # 2=KR
    (Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"), 2),
    (Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"), 0),
    (Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"), 0),
    (Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"), 0),
    (Path("C:/Windows/Fonts/malgun.ttf"), 0),
]
_BOLD_CANDIDATES = [
    (PROJECT_DIR / "fonts" / "NotoSansKR-Bold.otf", 0),
    (PROJECT_DIR / "fonts" / "NotoSansKR-Bold.ttf", 0),
    (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"), 2),
    (Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"), 2),
    (Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"), 0),
    (Path("C:/Windows/Fonts/malgunbd.ttf"), 0),
    # 볼드 전용 후보가 하나도 안 맞으면, 굵기 위계는 포기하되 한글이 아예 안
    # 보이는 것보단 나으니 Regular 후보로 다시 한번 시도한다 (find_font가 처리).
]


def _env_override(env_var: str):
    path = os.environ.get(env_var)
    if not path:
        return None
    index = int(os.environ.get(env_var + "_INDEX", "0"))
    return Path(path), index


def find_font_path(candidates: list, env_var: str):
    """후보를 순서대로 확인해서 실제로 존재하는 첫 폰트의 (경로, ttc index)를
    반환한다. 아무것도 없으면 None."""
    override = _env_override(env_var)
    if override and override[0].exists():
        return override
    for path, index in candidates:
        if path.exists():
            return path, index
    return None


def load_fonts():
    """제목/요약제목/본문/포인트/라벨용 폰트를 필요한 크기로 미리 만들어둔다.
    볼드 폰트를 못 찾으면 Regular 폰트로라도 대체해서(굵기 위계는 포기하지만)
    최소한 한글이 깨지지 않게 한다."""
    regular_hit = find_font_path(_REGULAR_CANDIDATES, "FONT_REGULAR_PATH")
    if regular_hit is None:
        raise SystemExit(
            "한글이 보이는 폰트를 찾지 못했습니다.\n"
            f"'{PROJECT_DIR / 'fonts'}' 폴더를 만들고 Noto Sans KR(무료, "
            "https://fonts.google.com/noto/specimen/Noto+Sans+KR)의 Regular/Bold를 "
            "NotoSansKR-Regular.otf / NotoSansKR-Bold.otf 이름으로 넣어주세요.\n"
            "다른 경로의 폰트를 쓰려면 FONT_REGULAR_PATH / FONT_BOLD_PATH 환경변수로 "
            "지정할 수 있습니다."
        )
    bold_hit = find_font_path(_BOLD_CANDIDATES, "FONT_BOLD_PATH") or regular_hit

    reg_path, reg_idx = regular_hit
    bold_path, bold_idx = bold_hit

    def make(path, index, size):
        return ImageFont.truetype(str(path), size=size, index=index)

    return {
        "title": make(bold_path, bold_idx, TITLE_SIZE),
        "heading": make(bold_path, bold_idx, HEADING_SIZE),
        "body": make(reg_path, reg_idx, BODY_SIZE),
        "body_bold": make(bold_path, bold_idx, BODY_SIZE),
        "point": make(bold_path, bold_idx, POINT_SIZE),
        "label": make(bold_path, bold_idx, LABEL_SIZE),
        # 표지 제목은 글자 수에 따라 크기를 동적으로 키운다(짧고 강렬한 제목일수록
        # 더 큼직하게 — "표지에 임팩트가 없다"는 피드백 반영). 고정 크기 폰트
        # 몇 개로는 부족해서, 임의 크기를 바로 만들 수 있게 함수를 같이 넘긴다.
        "title_maker": lambda size: make(bold_path, bold_idx, size),
    }


# ---------------------------------------------------------------------------
# 텍스트 줄바꿈 + **강조** 마크업
# ---------------------------------------------------------------------------

# 줄바꿈 계산(wrap_tokens)은 실제 이미지 픽셀과 무관하게 폰트 메트릭만 있으면
# 되므로, 매 카드 이미지를 만들기 전에 이 더미 draw로 먼저 계산해서 텍스트가
# 몇 줄인지/블록 높이가 얼마인지 알아낸다. 이걸 알아야 박스 라벨 크기와 본문이
# 겹치지 않는 위치를 "텍스트가 실제로 차지하는 자리"에 맞춰 미리 잡을 수 있다.
_MEASURE_DRAW = ImageDraw.Draw(Image.new("RGB", (10, 10)))

_ACCENT_RE = re.compile(r"\*\*(.+?)\*\*")


def _tokenize(text: str) -> list:
    """텍스트를 "단어" 단위로 쪼개되, 각 단어는 (부분문자열, is_accent) 서식
    런의 리스트로 표현한다 — 반환값: [[(chunk, accent), ...], ...] (바깥
    리스트가 단어, 안쪽이 그 단어를 이루는 서식 런).

    단순히 "**로 감싼 부분만 공백 기준으로 쪼갠다"고 하면, 강조 구간이 조사
    (을/를/은/는/로 등)와 공백 없이 바로 붙어 있는 아주 흔한 한국어 패턴
    ("**보습과 진정**을", "**클렌저**로")에서 그 경계가 단어 중간에 있는데도
    없던 공백이 생긴 것처럼 렌더링돼 문법이 깨져 보인다. 그래서 원문의 공백
    위치는 그대로 보존하고, ** 경계가 단어 중간에 걸리면 그 단어 하나를
    서식이 다른 두 런으로 나눠서(공백 없이 이어 그리도록) 표현한다."""
    words = []
    current = []
    for run_text, accent in (
        (part[2:-2], True) if part.startswith("**") and part.endswith("**") and len(part) >= 4 else (part, False)
        for part in re.split(r"(\*\*.+?\*\*)", text)
        if part
    ):
        for piece in re.split(r"(\s+)", run_text):
            if piece == "":
                continue
            if piece.isspace():
                if current:
                    words.append(current)
                    current = []
                continue
            current.append((piece, accent))
    if current:
        words.append(current)
    return words


def wrap_tokens(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    """단어(토큰) 단위로 max_width 안에 들어가게 줄바꿈한다. 한 단어이 그
    자체로 max_width보다 길면(거의 없지만 안전장치로, 이 경우 서식은 포기하고)
    글자 단위로 쪼갠다. 폰트 메트릭만 있으면 계산되므로 실제 카드 이미지가
    아직 없어도 미리 호출할 수 있다 — 모듈 상단의 _MEASURE_DRAW를 씀. 강조(**)
    구간은 실제 렌더링 때 볼드 폰트로 그려지는데, 너비 차이가 커봐야 몇
    픽셀이라 줄바꿈 계산은 이 함수에 넘긴 폰트 하나 기준으로 근사한다."""
    draw = _MEASURE_DRAW
    space_w = draw.textlength(" ", font=font)
    lines, current, current_w = [], [], 0.0

    def word_width(word_runs):
        return sum(draw.textlength(chunk, font=font) for chunk, _ in word_runs)

    def flush():
        if current:
            lines.append(list(current))
            current.clear()

    for word_runs in _tokenize(text):
        w = word_width(word_runs)
        if w > max_width:
            # 단어 하나가 통째로 너무 길면(거의 없음) 서식은 포기하고 글자
            # 단위로 쪼개서 강제로 줄바꿈한다.
            flush()
            plain = "".join(chunk for chunk, _ in word_runs)
            accent = word_runs[0][1] if word_runs else False
            chunk_buf = ""
            for ch in plain:
                if draw.textlength(chunk_buf + ch, font=font) > max_width and chunk_buf:
                    lines.append([[(chunk_buf, accent)]])
                    chunk_buf = ch
                else:
                    chunk_buf += ch
            if chunk_buf:
                current.append([(chunk_buf, accent)])
                current_w = draw.textlength(chunk_buf, font=font)
            continue

        added_w = w if not current else current_w + space_w + w
        if added_w > max_width and current:
            flush()
            current_w = 0.0
            added_w = w
        current.append(word_runs)
        current_w = added_w

    flush()
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    lines: list,
    x: int,
    top_y: int,
    line_height: int,
    align: str = "left",
    font_normal: ImageFont.FreeTypeFont = None,
    font_accent: ImageFont.FreeTypeFont = None,
    fill_normal=COLOR_TEXT,
    fill_accent=COLOR_ACCENT,
    stroke_width: int = 0,
    stroke_fill=None,
) -> int:
    """wrap_tokens()가 만든 줄들을 그리고, 마지막 줄 다음 y좌표를 반환한다
    (다음 텍스트 블록을 이어붙일 때 씀). align="left"면 x를 왼쪽 기준선으로,
    "center"면 x를 가운데 기준으로 쓴다. font_accent를 font_normal과 다르게
    주면(예: 볼드 폰트) 강조(**) 구간만 그 폰트로 그려서 색이 아니라 굵기로도
    강조할 수 있다 — font_accent를 안 주면 font_normal과 같은 폰트를 쓰고
    fill_accent 색으로만 구분된다. 한 단어 안에 서식이 다른 런이 여러 개
    있어도(예: "클렌저"(볼드)+"로"(보통)) 그 사이엔 공백을 넣지 않고 이어
    그린다 — 단어와 단어 사이에만 공백 하나를 둔다.

    stroke_width/stroke_fill을 주면 글자 테두리에 어두운 외곽선을 둘러서,
    사진 위에 스크림(어두운 반투명 배경) 없이도 밝은 사진 위에서 흰 글자가
    묻히지 않게 한다 — "글씨 뒤에 검은 배경이 깔리는 게 이상하다"는 피드백으로
    스크림을 없앤 자리를 대신한다. textlength는 stroke_width를 계산에 안 넣어서
    커서 위치는 외곽선 없는 폭 기준으로 살짝 좁게 잡히지만, 외곽선 두께가
    작아서(2~4px) 눈에 띄는 겹침은 없다."""
    font_accent = font_accent or font_normal
    space_w = draw.textlength(" ", font=font_normal)

    def word_width(word_runs):
        return sum(draw.textlength(chunk, font=(font_accent if a else font_normal)) for chunk, a in word_runs)

    y = top_y
    for line in lines:
        widths = [word_width(w) for w in line]
        line_w = sum(widths) + space_w * max(0, len(line) - 1)
        cursor = x if align == "left" else x - line_w / 2
        for word_runs in line:
            for chunk, accent in word_runs:
                font = font_accent if accent else font_normal
                draw.text(
                    (cursor, y), chunk, font=font, fill=fill_accent if accent else fill_normal,
                    stroke_width=stroke_width, stroke_fill=stroke_fill,
                )
                cursor += draw.textlength(chunk, font=font)
            cursor += space_w
        y += line_height
    return y


# ---------------------------------------------------------------------------
# 배경(사진 또는 대체 배경) + 박스 라벨
# ---------------------------------------------------------------------------

def load_background(local_path) -> Image.Image:
    """카드에 배정된 사진을 1080x1350 그대로 불러온다. 사진수집가/크롭 단계에서
    이미지를 못 찾은 카드(local_path가 None)라도 전체 파이프라인이 죽지 않게,
    계정 웜+뮤트 톤과 어울리는 짙은 단색 배경으로 대체한다."""
    if local_path:
        img_path = PROJECT_DIR / local_path
        if img_path.exists():
            img = Image.open(img_path).convert("RGB")
            if img.size != (CANVAS_W, CANVAS_H):
                img = img.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
            return img.convert("RGBA")
    return Image.new("RGBA", (CANVAS_W, CANVAS_H), (*COLOR_SCRIM, 255))


def render_box_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    edge_x: int,
    top_y: int,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    prefix: str = "",
    style: str = "light",
    align: str = "left",
    is_point: bool = False,
) -> int:
    """텍스트를 줄바꿈해서 그 블록 크기에 딱 맞는 각진 테두리 박스를 뒤에
    깔고 그린다. 요약 제목/포인트 칩이 이 함수를 공유해서 "사진 밝기와
    무관하게 항상 읽히는 박스 라벨"이라는 같은 시각 언어를 쓴다.

    style("light"/"dark")과 align("left"/"right")은 카드마다 사진을 보고
    Claude가 고른 값을 그대로 받는다 — 박스가 모든 카드에서 항상 흰색·왼쪽
    상단으로 똑같이 나오면 단조롭다는 피드백을 받고, 사진 톤/구도에 맞춰
    박스 배색과 좌우 위치가 카드마다 달라지게 했다. align="right"면 edge_x를
    "오른쪽 여백선"으로 보고 박스를 거기서부터 왼쪽으로 채운다(반대로
    "left"면 edge_x가 왼쪽 시작선). 이 함수를 안 부르면(heading/point가
    없을 때) 박스 자체가 카드에 안 들어간다 — 모든 카드에 박스를 강제로
    넣지 않는다. 다음 요소를 이어붙일 y좌표(여백 포함)를 반환한다."""
    colors = BOX_STYLES.get(style, BOX_STYLES["light"])
    text_color = colors["point_text"] if is_point else colors["text"]

    full_text = f"{prefix}{text}" if prefix else text
    lines = wrap_tokens(full_text, font, max_width)
    if not lines:
        return top_y

    line_height = int(font.size * 1.3)
    pad_x, pad_y = 18, 12
    space_w = draw.textlength(" ", font=font)

    def line_width(line):
        word_ws = [sum(draw.textlength(chunk, font=font) for chunk, _ in word) for word in line]
        return sum(word_ws) + space_w * max(0, len(line) - 1)

    max_line_w = max(line_width(line) for line in lines)
    last_line_bottom = top_y + (len(lines) - 1) * line_height + font.size

    text_x = edge_x if align == "left" else edge_x - max_line_w
    box = [text_x - pad_x, top_y - pad_y, text_x + max_line_w + pad_x, last_line_bottom + pad_y]
    draw.rectangle(box, fill=colors["bg"])  # 테두리 선 없이 배경색만 채운다 — 선으로 둘러싸인 느낌이 싫다는 피드백
    draw_wrapped(draw, lines, text_x, top_y, line_height, align="left", font_normal=font, fill_normal=text_color)

    return int(box[3]) + 20


# ---------------------------------------------------------------------------
# 카드별 요약 제목 / 강조 / 포인트 — Claude 주석 생성
# ---------------------------------------------------------------------------

ANNOTATE_TOOL = {
    "name": "submit_annotations",
    "description": "카드뉴스 세트 전체(표지 포함) 실제 사진을 보고 디자인 요소(세트 공통 박스 배색, 표지 제목/정렬, 카드별 요약 제목/포인트와 그 위치, 문장 강조)를 판단해서 만든다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "box_style": {
                "type": "string",
                "enum": ["light", "dark"],
                "description": "요약 제목/포인트 박스에 카드 세트 전체에서 통일해서 쓸 배색을 딱 하나만 고르세요(사진수집가가 세트 전체 톤을 한 번만 정하는 것과 같은 원리). 사진들 전체적인 밝기/분위기를 보고, 흰 배경(light)이 나을지 짙은 반투명 배경(dark)이 나을지 판단하세요. 카드마다 다르게 섞으면 안 됩니다 — 통일감이 중요합니다.",
            },
            "cards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "카드 번호"},
                        "cover_kicker": {
                            "type": "string",
                            "description": "표지 카드일 때만 채움. 제목 바로 위에 작은 글씨로 들어갈 소개 문구(예: '지성 피부 관리법', 4~12자) — 제목만 있으면 무슨 내용인지 감이 안 와서 밍밍해 보이니, 이 카드뉴스가 뭘 다루는지 한눈에 알려주는 짧은 태그라인. 표지가 아니면 빈 문자열.",
                        },
                        "cover_title": {
                            "type": "string",
                            "description": "표지 카드일 때만 채움. 짧고 강렬한 표지 제목(5~14자). 그 안에서 가장 강조하고 싶은 한 단어/구절은 **로 감싸도 됨(예: '번들거림의 **진짜 이유**'). 표지가 아니면 빈 문자열.",
                        },
                        "cover_align": {
                            "type": "string",
                            "enum": ["bottom-left", "center", "top-left"],
                            "description": "표지 사진을 보고 제목(+킥커)을 어디에 놓을지. 인물/피사체가 이미 화면 아래쪽에 있으면 top-left, 사진이 비교적 비어있고 임팩트를 줄 수 있으면 center, 그 외엔 bottom-left. 표지가 아니면 아무 값이나 둬도 무시됨.",
                        },
                        "heading": {
                            "type": "string",
                            "description": "본문 카드에서, 사진+문구를 보고 짧은 제목이 실제로 도움이 될 때만 채움(4~14자). 필요 없으면 빈 문자열. 사진이 이미 내용을 충분히 보여주면 넣지 않는 카드가 있는 게 자연스럽다.",
                        },
                        "body": {
                            "type": "string",
                            "description": "본문 카드에서, 원문 문장을 토씨 하나 바꾸지 말고 그대로 두되 가장 중요한 구간만 **로 감싸서 강조. 강조할 곳이 뚜렷하지 않으면 원문 그대로. 표지는 빈 문자열.",
                        },
                        "point": {
                            "type": "string",
                            "description": "본문 카드에서 한 줄로 뽑아낼 만한 뚜렷한 핵심 포인트(6~16자)가 있으면 적고, 없으면 빈 문자열. 모든 카드에 다 넣지 말 것.",
                        },
                        "align": {
                            "type": "string",
                            "enum": ["left", "right"],
                            "description": "heading/point 박스를 화면 왼쪽에 붙일지 오른쪽에 붙일지. 사진 속 인물/피사체가 없는 쪽(여백)에 배치하세요.",
                        },
                        "box_vpos": {
                            "type": "string",
                            "enum": ["top", "middle"],
                            "description": "heading/point 박스를 사진 위쪽(top, 기본)에 둘지, 사진 중간 여백(middle)에 둘지. 상단이 인물 얼굴 등으로 이미 꽉 차 있으면 middle을 고르세요. 박스가 없는 카드면 아무 값이나 둬도 무시됨.",
                        },
                    },
                    "required": ["index", "cover_kicker", "cover_title", "cover_align", "heading", "body", "point", "align", "box_vpos"],
                },
            },
        },
        "required": ["box_style", "cards"],
    },
}


def _local_image_block(local_path):
    """카드에 배정된 로컬 이미지를 Claude 메시지에 넣을 base64 이미지
    블록으로 바꾼다. annotate_cards가 문구뿐 아니라 실제 사진 분위기도 보고
    판단하게 하기 위함(예: 사진이 이미 여백이 없으면 요약 제목을 굳이 안
    붙이는 식). 원본 그대로 보낼 필요는 없어서 작게 리사이즈해 토큰을 아낀다.
    실패하면 None — 호출하는 쪽에서 문구만으로 판단하게 넘어간다."""
    if not local_path:
        return None
    img_path = PROJECT_DIR / local_path
    if not img_path.exists():
        return None
    try:
        img = Image.open(img_path).convert("RGB")
        img.thumbnail((360, 450))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}
    except Exception:
        return None


def _normalize_for_compare(text: str) -> str:
    """공백만 다른 건 같은 문장으로 보기 위한 느슨한 비교용 정규화."""
    return " ".join(text.split())


def annotate_cards(client: anthropic.Anthropic, script: dict, manifest: list) -> dict:
    """카드마다(표지 포함) 실제로 배정된 사진과 문구를 같이 Claude에게 보여주고
    (1) 표지면 짧고 강렬한 표지 제목 (2) 본문이면 필요할 때만 요약 제목/포인트
    (3) 본문이면 **강조** 표시가 추가된 본문을 한 번에 만들게 한다. 문구만
    보고 판단하지 않고 사진도 같이 보내는 이유는 "이미지랑 대본을 같이 보고
    디자인하라"는 요청 때문 — 카드마다 박스를 넣을지 말지, 어디를 강조할지가
    사진 분위기에 따라서도 달라져야 한다.

    카드마다 API를 따로 부르지 않고 전체를 한 번에 보내는 이유는, 그래야
    Claude가 카드 사이의 균형(예: 포인트를 너무 많은/적은 카드에 넣지 않기)을
    보고 판단할 수 있고 API 호출 비용도 줄기 때문이다.

    안전장치: Claude가 돌려준 body에서 **를 다 지웠을 때 원문과 다르면(문장을
    새로 쓰거나 단어를 바꾼 경우) 강조를 포기하고 원문 그대로 쓴다 — PM 승인을
    받은 문구를 디자이너 단계에서 임의로 바꾸면 안 되기 때문이다. 다만 완전히
    똑같은 문자열만 통과시키면 공백 하나 차이로도 강조가 통째로 날아가는 일이
    잦아서(실제로 그래서 "볼드체가 하나도 안 됐다"는 피드백을 받았음), 공백
    차이는 무시하고 비교한다."""
    if not manifest:
        return {}

    system_prompt = """당신은 스킨케어 카드뉴스의 디자이너입니다. 각 카드의 실제 사진과 문구를
같이 보고 판단하세요. PM 승인을 받은 본문 문장 자체(** 강조 마크 제외)는 절대
바꾸지 마세요. 카드마다 해당 없는 필드는 빈 문자열("")로 두세요 — 모든 카드에
모든 요소를 다 넣을 필요는 없습니다. 오히려 필요 없는데 억지로 채우면 안
됩니다. 카드 역할이 "표지"면 cover_* 필드만, "마무리"면 아무 필드도 채우지
마세요(마무리 카드 문구는 여기서 다루지 않고 별도 CTA 템플릿으로 렌더링되니
전부 빈 문자열로 둠). 그 외 카드가 "본문 카드"입니다.

가장 중요한 원칙: 색/스타일은 세트 전체가 하나로 통일돼야 하고(카드마다 흰
박스/검정 박스가 섞이면 산만하고 통일감이 없어 보입니다), 위치/구성은 오히려
카드마다 사진에 맞게 자유롭게 달라져도 됩니다(그래야 캐러셀이 단조롭지
않습니다). 즉 "색은 하나로, 배치는 다양하게"입니다.

- box_style (세트 전체에 딱 하나, cards 배열 밖에 있는 필드): 카드 9장의
  사진들을 전체적으로 보고 흰 배경(light) 또는 짙은 반투명 배경(dark) 중
  이 세트 전체 무드에 어울리는 쪽을 하나만 고르세요. 이게 모든 카드의
  heading/point 박스에 똑같이 적용됩니다.
- cover_kicker (표지 카드에만): 제목 바로 위에 작은 글씨로 들어갈 소개
  문구(4~12자, 예: "지성 피부 관리법"). 제목만 있으면 무슨 내용인지 감이
  안 와서 밍밍해 보이니, 이 카드뉴스 전체가 뭘 다루는지 알려주는 태그라인을
  붙이세요.
- cover_title (표지 카드에만): 원래 hook 문장은 카드 안에서 읽는 대사체라
  길고 늘어지는 경우가 많습니다. 표지 이미지에 큼직하게 들어갈 제목은 그
  문장을 그대로 쓰지 말고, 스크롤을 멈추게 할 만큼 짧고 강렬하게(5~14자
  정도) 새로 뽑으세요. 완전한 문장이 아니어도 됩니다. 그 안에서 가장 강조할
  단어/구절 하나는 **로 감싸도 됩니다(예: "번들거림의 **진짜 이유**").
- cover_align (표지 카드에만): 사진 속 인물/피사체가 어디 있는지 보고
  제목(+킥커)이 겹치지 않을 위치를 고르세요.
- heading (본문 카드에만): 사진+문구를 같이 보고, 짧은 제목 하나가 이 카드를
  더 잘 전달한다고 판단될 때만(4~14자) 채우세요. 문장 자체가 이미 짧고
  명확하거나, 사진이 이미 내용을 충분히 보여주면 억지로 만들지 말고 빈
  문자열로 두세요. 카드 9장 중 절반 이상은 비워도 괜찮습니다.
- body (본문 카드에만): 원문 문장을 토씨 하나 바꾸지 말고 그대로 두되, 그 중
  가장 중요한 구간 한두 곳만 **로 감싸서 강조하세요(예: "**수분 부족**이
  원인"). 강조할 만한 곳이 뚜렷하지 않으면 강조 없이 원문 그대로 반환해도
  됩니다.
- point (본문 카드에만): 한 줄로 뽑아낼 만한 뚜렷한 핵심 포인트(6~16자)가
  있을 때만 적으세요. 정보 전달용 카드엔 자연스럽게 어울리지만, 공감/전환
  유도용 문장에는 억지로 만들지 마세요.
- align/box_vpos (본문 카드에만, heading이나 point를 하나라도 채웠을 때만
  의미 있음): 그 카드 사진에서 인물/피사체가 없는 여백 쪽으로 박스 위치를
  고르세요(왼쪽/오른쪽, 위쪽/중간). 카드마다 달라도 됩니다 — 오히려 매번
  똑같은 자리면 단조롭습니다.

submit_annotations 도구로만 응답하세요."""

    content = [{"type": "text", "text": f"주제: {script.get('topic', '')}\n\n아래는 카드 {len(manifest)}장의 사진과 문구입니다."}]
    for c in manifest:
        content.append({"type": "text", "text": f"[카드 {c['index']}] 역할: {c['role']}\n문구: {c['text']}"})
        img_block = _local_image_block(c.get("local_path"))
        content.append(img_block if img_block else {"type": "text", "text": "(사진 없음)"})

    response = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        system=system_prompt,
        tools=[ANNOTATE_TOOL],
        tool_choice={"type": "tool", "name": "submit_annotations"},
        messages=[{"role": "user", "content": content}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_annotations":
            # box_style은 카드마다 따로 정하지 않고 세트 전체에 하나만 적용한다
            # (사진마다 흰 박스/검정 박스가 섞이면 산만하고 통일감이 없어
            # 보인다는 피드백을 받았음) — cards 배열 밖의 최상위 필드 하나를
            # 모든 카드에 그대로 복사해서 쓴다.
            set_box_style = block.input.get("box_style") if block.input.get("box_style") in ("light", "dark") else "light"

            result = {}
            originals = {c["index"]: c["text"] for c in manifest}
            for c in block.input.get("cards", []):
                idx = c.get("index")
                original = originals.get(idx)
                if original is None:
                    continue
                body = c.get("body") or original
                if _normalize_for_compare(body.replace("**", "")) != _normalize_for_compare(original):
                    print(f"    (카드 {idx}: 강조하면서 원문이 살짝 달라져서 강조 없이 원문 그대로 사용)")
                    body = original
                result[idx] = {
                    "cover_kicker": (c.get("cover_kicker") or "").strip() or None,
                    "cover_title": (c.get("cover_title") or "").strip() or None,
                    "cover_align": c.get("cover_align") if c.get("cover_align") in ("bottom-left", "center", "top-left") else None,
                    "heading": (c.get("heading") or "").strip() or None,
                    "annotated_text": body,
                    "point": (c.get("point") or "").strip() or None,
                    "box_style": set_box_style,
                    "box_align": c.get("align") if c.get("align") in ("left", "right") else "left",
                    "box_vpos": c.get("box_vpos") if c.get("box_vpos") in ("top", "middle") else "top",
                }
            return result
    return {}


# ---------------------------------------------------------------------------
# 3종 템플릿
# ---------------------------------------------------------------------------

def _title_font_size(title_text: str) -> int:
    """제목 글자 수에 따라 표지 폰트 크기를 동적으로 키운다. 표지 제목을
    짧고 강렬하게 뽑아도(cover_title) 항상 같은 크기(72px)로만 찍으면
    "임팩트가 없다"는 인상을 줘서, 짧을수록 더 큼직하게 키워 포스터처럼
    보이게 한다. **/공백을 뺀 순수 글자 수 기준."""
    visible_len = len(re.sub(r"\*\*", "", title_text).replace(" ", ""))
    if visible_len <= 8:
        return 108
    if visible_len <= 14:
        return 86
    return TITLE_SIZE


def render_header_card(card: dict, fonts: dict) -> Image.Image:
    """1번 카드(표지) 템플릿. 제목은 대본의 hook 문장을 그대로 쓰지 않는다 —
    hook은 "얼굴은 번들거리는데 속은 당기고... 이거 저만 그런가요?ㅠㅠ" 처럼
    카드 안에서 읽는 대사체라 표지 이미지 제목으로 쓰기엔 길고 늘어진다는
    피드백을 받았다. 대신 annotate_cards()가 만든 cover_title(짧고 강렬한
    제목)을 쓰고, 없으면(API 키 없음 등) hook 원문으로 폴백한다.

    제목 바로 위에 작은 킥커 문구(cover_kicker, 예: "지성 피부 관리법")를
    한 줄 더 얹는다 — 제목 한 줄만 있으면 "뭔 내용인지 감이 안 와서 밍밍하다"는
    피드백을 받았다. 참고 레퍼런스도 작은 소개 문구 + 큰 제목을 함께 쓴다.

    제목이 짧을수록 폰트를 더 키우고(_title_font_size), cover_align에 따라
    표지 사진 구도에 맞는 배치(하단좌측/가운데/상단좌측) 중 하나를 쓴다 —
    표지가 매번 똑같은 자리에 똑같은 크기로만 나오면 임팩트가 없다는 피드백
    반영. 사진에 여백이 없을 때(annotate_cards가 판단 못 했을 때)는 기존
    방식(하단좌측)으로 안전하게 폴백한다."""
    title_text = card.get("cover_title") or card["text"]
    kicker_text = card.get("cover_kicker")
    align = card.get("cover_align") or "bottom-left"

    size = _title_font_size(title_text)
    title_font = fonts["title_maker"](size)
    line_height = int(size * 1.25)

    x_align = "center" if align == "center" else "left"
    max_w = CONTENT_WIDTH if align != "center" else int(CONTENT_WIDTH * 0.85)
    lines = wrap_tokens(title_text, title_font, max_w)
    title_block_height = line_height * len(lines)

    kicker_line_height = int(LABEL_SIZE * 1.4)
    kicker_gap = 10
    kicker_lines = wrap_tokens(kicker_text, fonts["label"], max_w) if kicker_text else []
    kicker_block_height = kicker_line_height * len(kicker_lines) + (kicker_gap if kicker_lines else 0)

    total_height = kicker_block_height + title_block_height

    if align == "top-left":
        block_top = SAFE_TOP + CONTENT_TOP_PAD
    elif align == "center":
        block_top = SAFE_TOP + (SAFE_BOTTOM - SAFE_TOP - total_height) // 2
    else:  # bottom-left
        block_top = SAFE_BOTTOM - total_height

    bg = load_background(card.get("local_path"))
    draw = ImageDraw.Draw(bg)

    x = CANVAS_W // 2 if x_align == "center" else CONTENT_MARGIN_X
    title_top = block_top
    if kicker_lines:
        draw_wrapped(
            draw, kicker_lines, x, block_top, kicker_line_height, align=x_align,
            font_normal=fonts["label"], fill_normal=COLOR_ACCENT,
            stroke_width=2, stroke_fill=COLOR_STROKE,
        )
        title_top = block_top + kicker_block_height

    draw_wrapped(
        draw, lines, x, title_top, line_height, align=x_align, font_normal=title_font,
        stroke_width=4, stroke_fill=COLOR_STROKE,
    )

    return bg.convert("RGB")


def render_body_card(card: dict, fonts: dict) -> Image.Image:
    """2~N번 카드(슬라이드 본문) 템플릿: (있으면) 요약 제목 박스 → (있으면)
    포인트 칩 → 본문 문단 순으로 왼쪽 정렬로 쌓는다. 본문은 항상 하단
    고정이고, 위쪽 요소(요약 제목/포인트)가 유난히 길어서 겹칠 것 같으면
    본문을 그 아래로 내려서 배치한다.

    요약 제목/포인트는 둘 다 선택 사항이다 — annotate_cards()가 카드 사진과
    문구를 같이 보고 "이 카드에 실제로 도움이 될 때만" 채우도록 판단하므로,
    모든 카드에 박스가 다 들어가지는 않는다(내용에 안 맞으면 아예 생략).
    "요약 제목"은 본문 문장을 그대로 잘라 위로 올리는 게 아니라(문장이 중간에
    끊겨 보이는 문제가 있었음) Claude가 새로 뽑은 짧은 문구를 쓴다 —
    annotate_cards()가 없으면(ANTHROPIC_API_KEY 미설정 등) heading/point 없이
    본문만 렌더링된다."""
    heading = card.get("heading")
    point = card.get("point")
    body_text = card.get("annotated_text") or card["text"]
    box_style = card.get("box_style", "light")
    box_align = card.get("box_align", "left")
    edge_x = CONTENT_MARGIN_X if box_align == "left" else CANVAS_W - CONTENT_MARGIN_X
    # 박스 색은 세트 전체에서 통일되지만(box_style), 그 자리(맨 위/중간)는
    # 카드마다 사진의 여백 위치에 맞게 자유롭게 달라져도 된다는 피드백을
    # 반영해 box_vpos로 시작 y를 다르게 잡는다 — "색은 하나로, 배치는
    # 다양하게".
    box_top_y = SAFE_TOP + CONTENT_TOP_PAD if card.get("box_vpos", "top") == "top" else SAFE_TOP + int((SAFE_BOTTOM - SAFE_TOP) * 0.32)

    body_lines = wrap_tokens(body_text, fonts["body"], CONTENT_WIDTH)
    body_line_height = int(BODY_SIZE * 1.5)
    body_block_height = body_line_height * len(body_lines)

    # 1) 위쪽 블록(요약 제목 + 포인트 칩)이 실제로 몇 픽셀을 차지하는지 더미
    # draw로 먼저 계산한다 — 이걸 알아야 본문이 겹치지 않는 위치를 알 수 있다.
    y = box_top_y
    if heading:
        y = render_box_text(_MEASURE_DRAW, heading, edge_x, y, fonts["heading"], CONTENT_WIDTH, style=box_style, align=box_align)
    if point:
        y = render_box_text(_MEASURE_DRAW, point, edge_x, y, fonts["point"], CONTENT_WIDTH, prefix="→ ", style=box_style, align=box_align, is_point=True)
    top_block_bottom = y

    body_top = SAFE_BOTTOM - body_block_height
    if body_top < top_block_bottom:
        body_top = top_block_bottom  # 부득이하게 겹치면 위쪽 블록 바로 아래로

    bg = load_background(card.get("local_path"))
    draw = ImageDraw.Draw(bg)

    y = box_top_y
    if heading:
        y = render_box_text(draw, heading, edge_x, y, fonts["heading"], CONTENT_WIDTH, style=box_style, align=box_align)
    if point:
        y = render_box_text(draw, point, edge_x, y, fonts["point"], CONTENT_WIDTH, prefix="→ ", style=box_style, align=box_align, is_point=True)

    draw_wrapped(
        draw, body_lines, CONTENT_MARGIN_X, body_top, body_line_height,
        align="left", font_normal=fonts["body"], font_accent=fonts["body_bold"],
        stroke_width=3, stroke_fill=COLOR_STROKE,
    )

    return bg.convert("RGB")


def render_closing_card(card: dict, fonts: dict) -> Image.Image:
    """마지막 카드(마무리) 템플릿: CTA + 댓글 유도 질문 + 계정 핸들을 왼쪽
    정렬로 배치한다. approved_script.json의 cta/comment_question은 어느
    슬라이드에도 안 묶여 있어서, 마지막 슬라이드 이미지를 재사용해 이 카드를
    새로 만든다."""
    bg = load_background(card.get("local_path"))
    draw = ImageDraw.Draw(bg)

    cta_lines = wrap_tokens(card["cta"], fonts["title"], CONTENT_WIDTH)
    cta_line_height = int(TITLE_SIZE * 1.25)
    y = int(CANVAS_H * 0.40)
    y = draw_wrapped(
        draw, cta_lines, CONTENT_MARGIN_X, y, cta_line_height, align="left",
        font_normal=fonts["title"], fill_normal=COLOR_ACCENT,
        stroke_width=4, stroke_fill=COLOR_STROKE,
    )

    y += 30
    q_lines = wrap_tokens(card["comment_question"], fonts["body"], CONTENT_WIDTH)
    q_line_height = int(BODY_SIZE * 1.35)
    draw_wrapped(
        draw, q_lines, CONTENT_MARGIN_X, y, q_line_height, align="left", font_normal=fonts["body"],
        stroke_width=3, stroke_fill=COLOR_STROKE,
    )

    draw.text(
        (CONTENT_MARGIN_X, SAFE_BOTTOM - LABEL_SIZE), ACCOUNT_HANDLE, font=fonts["label"], fill=COLOR_TEXT,
        stroke_width=2, stroke_fill=COLOR_STROKE,
    )

    return bg.convert("RGB")


# ---------------------------------------------------------------------------
# 파이프라인
# ---------------------------------------------------------------------------

def safe_filename(text: str, max_len: int = 12) -> str:
    keep = "".join(c for c in text if c.isalnum())
    return keep[:max_len] if keep else "card"


def build_cards(script: dict, manifest: list, annotations: dict = None) -> list:
    """crop_manifest.json의 각 카드(표지+슬라이드+마무리)를 렌더링 대상
    목록으로 만든다. annotations는 annotate_cards()가 만든
    {index: {heading, annotated_text, point, ...}} 맵.

    마무리 카드는 이제 photo_agent.py가 전용 사진을 따로 찾아서
    manifest 안에 role="마무리" 항목으로 들어있다 — 예전엔 마지막 슬라이드
    사진을 그대로 재사용해서 캐러셀 마지막 두 장이 같은 사진으로 겹쳐 보이는
    문제가 있었다. photo_agent.py를 다시 안 돌린 예전 crop_manifest.json
    (마무리 항목이 없는 버전)을 쓸 때는 예전처럼 마지막 슬라이드 사진을
    재사용하는 폴백으로 자동 전환한다 — API를 다시 안 불러도 파이프라인이
    죽지 않게."""
    annotations = annotations or {}
    fonts = load_fonts()

    results = []
    has_dedicated_closing = any(c.get("role") == "마무리" for c in manifest)
    for card in manifest:
        card = {**card, "topic": script.get("topic", ""), **annotations.get(card["index"], {})}
        if card["role"] == "표지":
            img = render_header_card(card, fonts)
        elif card["role"] == "마무리":
            closing_card = {
                "local_path": card.get("local_path"),
                "cta": script.get("cta", ""),
                "comment_question": script.get("comment_question", ""),
            }
            img = render_closing_card(closing_card, fonts)
        else:
            img = render_body_card(card, fonts)
        results.append((card["index"], card["role"], img))
        print(f"  카드 {card['index']}({card['role']}) 렌더링 완료")

    if not has_dedicated_closing:
        last_with_image = next((c for c in reversed(manifest) if c.get("local_path")), None)
        closing_card = {
            "local_path": last_with_image.get("local_path") if last_with_image else None,
            "cta": script.get("cta", ""),
            "comment_question": script.get("comment_question", ""),
        }
        closing_img = render_closing_card(closing_card, fonts)
        closing_index = (manifest[-1]["index"] + 1) if manifest else 1
        results.append((closing_index, "마무리", closing_img))
        print(
            f"  카드 {closing_index}(마무리) 렌더링 완료 "
            "(전용 사진이 없어 마지막 슬라이드 사진을 재사용 — photo_agent.py를 다시 돌리면 전용 사진으로 바뀝니다)"
        )

    return results


def build_demo_manifest(script: dict) -> list:
    """실제 사진(Unsplash/Pexels API 키 필요) 없이도 결과물을 눈으로 바로
    확인해볼 수 있게, approved_script.json에 있는 예시 대본 문구는 그대로
    쓰고 사진 자리에만 카드마다 다른 색의 단색 이미지를 채운 가짜
    crop_manifest.json을 만든다. `python designer_agent.py --demo`로 쓴다.
    images/, crop_manifest.json은 이미 .gitignore에 있어서 저장소를
    더럽히지 않는다."""
    images_dir = PROJECT_DIR / "images"
    images_dir.mkdir(exist_ok=True)

    cards = [{"index": 1, "role": "표지", "text": script["hook"]}]
    cards += [{"index": s["index"], "role": s["role"], "text": s["text"]} for s in script["slides"]]
    closing_text = f"{script.get('cta', '')} {script.get('comment_question', '')}".strip()
    cards.append({"index": cards[-1]["index"] + 1, "role": "마무리", "text": closing_text})

    manifest = []
    for i, card in enumerate(cards):
        hue = (i * 0.13) % 1.0
        r, g, b = (int(x * 255) for x in colorsys.hsv_to_rgb(hue, 0.35, 0.75))
        img = Image.new("RGB", (CANVAS_W, CANVAS_H), (r, g, b))
        filename = f"card_{card['index']:02d}_{safe_filename(card['role'])}.jpg"
        img.save(images_dir / filename, "JPEG", quality=90)
        manifest.append({**card, "local_path": f"images/{filename}"})

    return manifest


def check_approval_gate(force: bool = False):
    """approved_script.json이라는 이름과 달리, orchestrator.py는 3회 반려 끝에도
    통과 못 하면(max_revisions_reached) 그 미승인 마지막 시도본을 그대로 이
    파일에 저장한다. 이 확인이 없으면 반려 사유(단정적 표현, 이모티콘 누락 등)가
    그대로 최종 발행용 이미지로 렌더링될 수 있다. photo_agent.py의 동명 함수와
    같은 기준(review_log.json의 final_status)을 쓴다 — review_log.json이 아예
    없으면(대본을 수동으로 준비한 경우 등) 확인할 수단이 없으니 그냥 진행한다."""
    log_path = PROJECT_DIR / "review_log.json"
    if not log_path.exists():
        return
    try:
        log = json.loads(log_path.read_text(encoding="utf-8"))
    except Exception:
        return
    status = log.get("final_status")
    if status == "approved":
        return
    if force:
        print(
            f"(경고: review_log.json 기준 이 대본은 미승인 상태(final_status={status})입니다. "
            "--force로 강제 진행해요 — 반려 사유가 최종 이미지에 남아있을 수 있으니 확인하세요.)\n"
        )
        return
    raise SystemExit(
        f"{log_path}를 보니 이 대본은 아직 PM 승인을 못 받았습니다 "
        f"(final_status={status}, 시도 {log.get('attempts', '?')}회).\n"
        "이대로 최종 이미지를 만들면 반려 사유가 그대로 남을 수 있습니다.\n"
        "대본을 다시 손봐서 orchestrator.py를 재실행하거나, 그래도 지금 상태로 진행하려면 "
        "'python designer_agent.py --force'(--demo와 함께 써도 됨)로 실행하세요."
    )


def main():
    demo = "--demo" in sys.argv
    manifest_path = PROJECT_DIR / "crop_manifest.json"
    script_path = PROJECT_DIR / "approved_script.json"
    if not script_path.exists():
        raise SystemExit(f"{script_path} 이 없습니다. 먼저 orchestrator.py를 실행하세요.")
    check_approval_gate(force="--force" in sys.argv)
    script = json.loads(script_path.read_text(encoding="utf-8"))

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    elif demo:
        print("(--demo: 실제 사진 없이 단색 이미지로 대체해서 레이아웃만 미리 봅니다)\n")
        manifest = build_demo_manifest(script)
    else:
        raise SystemExit(
            f"{manifest_path} 이 없습니다. 먼저 crop_images.py를 실행하세요.\n"
            "실제 사진 없이 레이아웃만 빠르게 보고 싶으면 "
            "'python designer_agent.py --demo'로 실행하세요."
        )

    if ACCOUNT_HANDLE == "@계정핸들":
        print(
            "(참고: ACCOUNT_HANDLE 환경변수가 없어서 마무리 카드에 자리표시자 "
            "\"@계정핸들\"이 들어가요. 실제로 발행하기 전에 export ACCOUNT_HANDLE=\"@내계정\" "
            "으로 바꿔서 다시 실행하세요.)\n"
        )

    annotations = {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            print("Claude로 카드별 요약 제목/강조/포인트를 만드는 중...")
            annotations = annotate_cards(anthropic.Anthropic(), script, manifest)
        except Exception as e:
            print(f"(카드 주석 생성 실패, 요약 제목/강조/포인트 없이 계속 진행: {e})\n")
    else:
        print(
            "(참고: ANTHROPIC_API_KEY가 없어서 상단 요약 제목/강조/포인트 없이 기본 "
            "스타일로만 렌더링해요. export ANTHROPIC_API_KEY=... 하고 다시 실행하면 "
            "카드별로 요약 제목/볼드 강조/포인트 칩이 추가돼요.)\n"
        )

    print(f"'{script.get('topic', '')}' 카드뉴스 최종 이미지를 만듭니다...\n")
    cards = build_cards(script, manifest, annotations)

    final_dir = PROJECT_DIR / "final"
    final_dir.mkdir(exist_ok=True)

    final_manifest = []
    for index, role, img in cards:
        filename = f"card_{index:02d}_{safe_filename(role)}.png"
        out_path = final_dir / filename
        img.save(out_path, "PNG")
        final_manifest.append({"index": index, "role": role, "local_path": str(out_path.relative_to(PROJECT_DIR))})

    manifest_out = final_dir.parent / "final_manifest.json"
    manifest_out.write_text(json.dumps(final_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n총 {len(final_manifest)}장 완성 (표지 1 + 슬라이드 {len(final_manifest) - 2} + 마무리 1)")
    print(f"이미지 폴더: {final_dir}")
    print(f"매니페스트 저장: {manifest_out}")


if __name__ == "__main__":
    main()
