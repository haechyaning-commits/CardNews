"""
디자이너(Designer) 에이전트

crop_images.py가 만들어둔 로컬 이미지(crop_manifest.json + images/, 이미 1080x1350
4:5로 크롭되고 톤 보정까지 끝난 상태)에 작가가 쓴 문구를 얹어서 실제 인스타그램에
올릴 최종 카드뉴스 PNG를 만든다. Skill 문서 3번(디자이너 규칙)을 코드로 강제한다:

- 전체 슬라이드 4:5(1080x1350) 고정 — crop_images.py가 이미 보장하므로 여기선 그대로 사용.
- 템플릿 3종 고정: 헤더(표지) / 본문(슬라이드) / 마무리(CTA+댓글유도+핸들).
- 폰트 최대 2종(제목 1개 + 본문 1개, 굵기로 위계). 색상은 흰 텍스트 / 포인트색 /
  어두운 스크림(반투명 박스 역할) 3가지로 고정.
- 사진 위에 얹는 텍스트는 항상 어두운 그라데이션 스크림이나 반투명 박스 뒤에
  놓아서, 사진이 밝든 어둡든 가독성이 항상 확보되게 한다.
- 상하 15%는 프로필 아이콘/캡션 UI에 가려질 수 있는 세이프존이라 핵심 텍스트는
  그 안쪽에 배치한다.

레이아웃(v3): "문장이 중간에 끊겨 보인다", "카드마다 위치가 달라 산만하다"는
피드백을 반영해서 모든 본문 카드가 항상 같은 골격을 쓰되, 그 골격 안의 요소
구성은 카드 내용에 따라 달라지게 했다.
- 역할 태그(기존) 바로 아래에 그 카드 내용을 한눈에 보여주는 짧은 "요약 제목"을
  박스 라벨로 얹는다 — 본문 문장을 잘라 쓰는 게 아니라 Claude가 새로 짧게 뽑는다.
- 카드에 따라(정보성 카드 등) 뚜렷한 한 줄 "포인트"가 있으면 화살표 칩으로
  따로 배치한다. 모든 카드에 다 넣지는 않는다 — 내용에 안 맞으면 생략.
- 본문 문장은 원문 그대로(단어 하나도 안 바꿈) 두되, 그 중 가장 중요한 구간만
  볼드체로 강조한다.
- 전부 왼쪽 정렬로 통일해서(참고 레퍼런스 스타일) 카드마다 다른 배치가 아니라
  "같은 시스템, 다른 내용"으로 일관성을 준다.

이 요약 제목/강조 구간/포인트는 문장을 새로 쓰는 게 아니라 "어디를 강조할지"를
판단하는 작업이라 Claude 호출이 필요하다(annotate_cards). ANTHROPIC_API_KEY가
없으면 이 단계를 건너뛰고 요약 제목/강조/포인트 없이 기본 스타일로만 렌더링한다
— API 키가 없어도 파이프라인 자체는 죽지 않는다.

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
3. export ANTHROPIC_API_KEY="..." — 카드별 요약 제목/강조/포인트를 만드는 데 씀.
   없어도 실행은 되지만 그 세 가지 없이 기본 스타일로만 렌더링된다.
4. (필요하면) export ACCOUNT_HANDLE="@계정핸들" — 마무리 카드 하단에 표시된다.
   안 정하면 "@계정핸들"이 자리표시자로 들어가니 실제 발행 전에 바꿔야 한다.
5. python designer_agent.py

결과: final/ 폴더에 card_01_표지.png ~ card_09_마무리.png 로 저장되고,
각 카드의 최종 경로/역할이 담긴 final_manifest.json도 같이 생성된다.
"""

import json
import os
import re
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

# 역할 태그(작은 라벨) 한 줄이 차지하는 높이 + 요약 제목과의 간격.
TAG_RESERVE = 100

# 색상 팔레트: 텍스트(흰색) / 포인트(웜 톤 포인트색) / 스크림(검정, 텍스트
# 뒤에 까는 반투명 박스 역할) 3가지로 고정한다. 포인트색은 crop_images.py의
# 계정 고유 웜+뮤트 필터(붉은기를 살짝 올리는 방향)와 톤을 맞춰서 시리즈 전체가
# 하나의 색 느낌으로 보이게 골랐다.
COLOR_TEXT = (255, 255, 255, 255)
COLOR_ACCENT = (232, 176, 132, 255)
COLOR_SCRIM = (20, 15, 12)

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
        "label_regular": make(reg_path, reg_idx, LABEL_SIZE),
    }


# ---------------------------------------------------------------------------
# 텍스트 줄바꿈 + **강조** 마크업
# ---------------------------------------------------------------------------

# 줄바꿈 계산(wrap_tokens)은 실제 이미지 픽셀과 무관하게 폰트 메트릭만 있으면
# 되므로, 매 카드 이미지를 만들기 전에 이 더미 draw로 먼저 계산해서 텍스트가
# 몇 줄인지/블록 높이가 얼마인지 알아낸다. 이걸 알아야 스크림(어두운 그라데이션)과
# 박스 라벨 크기를 "텍스트가 실제로 차지하는 자리"에 맞춰 깔 수 있다.
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
) -> int:
    """wrap_tokens()가 만든 줄들을 그리고, 마지막 줄 다음 y좌표를 반환한다
    (다음 텍스트 블록을 이어붙일 때 씀). align="left"면 x를 왼쪽 기준선으로,
    "center"면 x를 가운데 기준으로 쓴다. font_accent를 font_normal과 다르게
    주면(예: 볼드 폰트) 강조(**) 구간만 그 폰트로 그려서 색이 아니라 굵기로도
    강조할 수 있다 — font_accent를 안 주면 font_normal과 같은 폰트를 쓰고
    fill_accent 색으로만 구분된다. 한 단어 안에 서식이 다른 런이 여러 개
    있어도(예: "클렌저"(볼드)+"로"(보통)) 그 사이엔 공백을 넣지 않고 이어
    그린다 — 단어와 단어 사이에만 공백 하나를 둔다."""
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
                draw.text((cursor, y), chunk, font=font, fill=fill_accent if accent else fill_normal)
                cursor += draw.textlength(chunk, font=font)
            cursor += space_w
        y += line_height
    return y


# ---------------------------------------------------------------------------
# 배경(사진 또는 대체 배경) + 스크림 + 박스 라벨
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


def _band_opacity(y: int, band_top: int, band_bottom: int, max_opacity: int, fade: int, min_opacity: int) -> float:
    """band_top~band_bottom 구간은 max_opacity, 그 위아래 fade 구간은
    min_opacity까지 서서히 옅어지고, 더 벗어난 곳은 min_opacity로 깔린다."""
    fade_in_start = max(0, band_top - fade)
    fade_out_end = band_bottom + fade
    if band_top <= y <= band_bottom:
        return max_opacity
    if y < band_top:
        if y <= fade_in_start:
            return min_opacity
        t = (y - fade_in_start) / max(1, band_top - fade_in_start)
        return min_opacity + (max_opacity - min_opacity) * t
    if y >= fade_out_end:
        return min_opacity
    t = (fade_out_end - y) / max(1, fade_out_end - band_bottom)
    return min_opacity + (max_opacity - min_opacity) * t


def add_scrim(img: Image.Image, bands: list, fade: int = 160, min_opacity: int = 40) -> Image.Image:
    """텍스트 블록이 있는 자리(band)만 어두워지는 스크림을 한 번에 깐다.
    bands는 [(band_top, band_bottom, max_opacity), ...] 목록. band_bottom을
    이미지 높이로 주면(표지/본문 하단처럼 텍스트가 맨 아래까지 이어질 때)
    아래쪽은 옅어지지 않고 가장자리까지 쭉 어둡게 유지된다."""
    w, h = img.size
    gradient = Image.new("L", (1, h), 0)
    for y in range(h):
        v = max(
            (_band_opacity(y, max(0, top), min(h, bottom), opacity, fade, min_opacity) for top, bottom, opacity in bands),
            default=min_opacity,
        )
        gradient.putpixel((0, y), int(v))
    gradient = gradient.resize((w, h))
    scrim = Image.new("RGBA", (w, h), (*COLOR_SCRIM, 255))
    scrim.putalpha(gradient)
    return Image.alpha_composite(img, scrim)


def add_full_scrim(img: Image.Image, opacity: int) -> Image.Image:
    """전체 화면에 균일한 반투명 검정을 깐다. 마무리 카드처럼 사진 위 전체에
    텍스트가 올라가는 경우, 위쪽만 어두운 그라데이션보다 균일한 스크림이 더
    안정적으로 읽힌다."""
    w, h = img.size
    scrim = Image.new("RGBA", (w, h), (*COLOR_SCRIM, opacity))
    return Image.alpha_composite(img, scrim)


def render_box_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    top_y: int,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    prefix: str = "",
    outline=None,
    text_color=COLOR_TEXT,
    fill_opacity: int = 170,
) -> int:
    """텍스트를 줄바꿈해서 그 블록 크기에 딱 맞는 반투명 박스를 뒤에 깔고
    왼쪽 정렬로 그린다. 역할 태그/요약 제목/포인트 칩이 전부 이 함수를 공유해서
    "사진 밝기와 무관하게 항상 읽히는 박스 라벨"이라는 같은 시각 언어를 쓴다
    (스크림 그라데이션과 달리, 사진의 밝은 부분 위에 떠 있어도 항상 보장됨).
    다음 요소를 이어붙일 y좌표(여백 포함)를 반환한다."""
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

    box = [x - pad_x, top_y - pad_y, x + max_line_w + pad_x, last_line_bottom + pad_y]
    draw.rounded_rectangle(box, radius=10, fill=(*COLOR_SCRIM, fill_opacity), outline=outline, width=2 if outline else 0)
    draw_wrapped(draw, lines, x, top_y, line_height, align="left", font_normal=font, fill_normal=text_color)

    return int(box[3]) + 20


# ---------------------------------------------------------------------------
# 카드별 요약 제목 / 강조 / 포인트 — Claude 주석 생성
# ---------------------------------------------------------------------------

ANNOTATE_TOOL = {
    "name": "submit_annotations",
    "description": "카드뉴스 슬라이드마다 상단 요약 제목, 강조 표시가 추가된 본문, (있다면) 핵심 포인트 한 줄을 만든다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "cards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "카드 번호"},
                        "heading": {
                            "type": "string",
                            "description": "이 카드 내용을 한눈에 보여주는 아주 짧은 제목(4~14자). 본문 문장을 그대로 자르지 말고 새로 짧게 요약할 것.",
                        },
                        "body": {
                            "type": "string",
                            "description": "원문 문장을 토씨 하나 바꾸지 말고 그대로 두되, 가장 중요한 구간 한두 곳만 **로 감싸서 강조 표시.",
                        },
                        "point": {
                            "type": "string",
                            "description": "이 카드에 한 줄로 뽑아낼 만한 뚜렷한 핵심 포인트(6~16자)가 있으면 적고, 없으면 빈 문자열.",
                        },
                    },
                    "required": ["index", "heading", "body", "point"],
                },
            },
        },
        "required": ["cards"],
    },
}


def annotate_cards(client: anthropic.Anthropic, script: dict, manifest: list) -> dict:
    """표지를 뺀 슬라이드 카드마다 (1) 상단 요약 제목 (2) **강조** 표시가
    추가된 본문 (3) 있으면 핵심 포인트 한 줄을 Claude에게 한 번에 만들게 한다.
    카드마다 API를 따로 부르지 않고 전체를 한 번에 보내는 이유는, 그래야
    Claude가 카드 사이의 균형(예: 포인트를 너무 많은/적은 카드에 넣지 않기)을
    보고 판단할 수 있고 API 호출 비용도 줄기 때문이다.

    안전장치: Claude가 돌려준 body에서 **를 다 지웠을 때 원문과 다르면(문장을
    새로 쓰거나 단어를 바꾼 경우) 강조를 포기하고 원문 그대로 쓴다 — PM 승인을
    받은 문구를 디자이너 단계에서 임의로 바꾸면 안 되기 때문이다."""
    body_cards = [c for c in manifest if c.get("role") != "표지"]
    if not body_cards:
        return {}

    lines = [f"[{c['index']}] ({c['role']}) {c['text']}" for c in body_cards]
    user_text = f"주제: {script.get('topic', '')}\n\n" + "\n".join(lines)

    system_prompt = """당신은 스킨케어 카드뉴스의 디자이너 보조입니다. PM 승인을 받은 대본
문구는 그대로 두고, 카드 디자인에 필요한 세 가지만 덧붙이세요.

1. heading: 이 카드가 무슨 내용인지 한눈에 보여주는 아주 짧은 제목(4~14자 정도).
   본문 문장을 그대로 잘라 쓰지 말고 새로 짧게 요약하세요.
2. body: 원문 문장을 토씨 하나 바꾸지 말고 그대로 두되, 그 중 가장 중요한
   구간 한두 곳만 **로 감싸서 강조 표시하세요 (예: "**수분 부족**이 원인").
   문장을 새로 쓰거나 단어를 바꾸면 안 됩니다.
3. point: 이 카드에 한 줄로 뽑아낼 만한 뚜렷한 핵심 포인트(6~16자)가 있으면
   적고, 없으면 빈 문자열("")로 두세요. 모든 카드에 다 넣을 필요는 없습니다 —
   정보 전달용 카드에는 자연스럽게 어울리지만, 공감/전환 유도용 문장에는
   억지로 만들지 마세요.

submit_annotations 도구로만 응답하세요."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system_prompt,
        tools=[ANNOTATE_TOOL],
        tool_choice={"type": "tool", "name": "submit_annotations"},
        messages=[{"role": "user", "content": user_text}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_annotations":
            result = {}
            originals = {c["index"]: c["text"] for c in body_cards}
            for c in block.input.get("cards", []):
                idx = c.get("index")
                original = originals.get(idx)
                if original is None:
                    continue
                body = c.get("body") or original
                if body.replace("**", "") != original:
                    body = original  # 원문이 바뀌었으면 강조 없이 원문 그대로
                result[idx] = {
                    "heading": (c.get("heading") or "").strip() or None,
                    "annotated_text": body,
                    "point": (c.get("point") or "").strip() or None,
                }
            return result
    return {}


# ---------------------------------------------------------------------------
# 3종 템플릿
# ---------------------------------------------------------------------------

def draw_role_tag(draw, label: str, fonts: dict):
    """세이프존 위쪽에 역할 태그(작은 포인트색 글씨) 박스 라벨을 배치한다.
    모든 본문/표지 카드가 공유하는 공통 요소. 페이지 번호("N/9")는 표지·
    본문·마무리 어디에도 안 넣기로 함(사용자 요청) — 캐러셀 자체가 이미
    번호를 보여주니 중복이라 뺐다."""
    y = SAFE_TOP
    pad_x, pad_y = 16, 10
    label_w = draw.textlength(label, font=fonts["label"])
    draw.rounded_rectangle(
        [CONTENT_MARGIN_X - pad_x, y - pad_y, CONTENT_MARGIN_X + label_w + pad_x, y + LABEL_SIZE + pad_y],
        radius=8,
        fill=(*COLOR_SCRIM, 140),
    )
    draw.text((CONTENT_MARGIN_X, y), label, font=fonts["label"], fill=COLOR_ACCENT)


def render_header_card(card: dict, fonts: dict) -> Image.Image:
    """1번 카드(표지) 템플릿: 주제 키워드를 작은 라벨로 hook 문구 바로 위에
    붙이고, 큰 제목을 하단 세이프존에 왼쪽 정렬로 배치한다(참고 레퍼런스의
    표지 구성 — 가운데 정렬 대신 하단좌측에 킥커+제목을 한 덩어리로)."""
    lines = wrap_tokens(card["text"], fonts["title"], CONTENT_WIDTH)
    line_height = int(TITLE_SIZE * 1.25)
    title_top = SAFE_BOTTOM - line_height * len(lines)

    bg = load_background(card.get("local_path"))
    bg = add_scrim(bg, bands=[(title_top, CANVAS_H, 205)])
    draw = ImageDraw.Draw(bg)

    draw_role_tag(draw, "표지", fonts)

    topic = card.get("topic", "")
    if topic:
        render_box_text(draw, topic, CONTENT_MARGIN_X, title_top - 62, fonts["label_regular"], CONTENT_WIDTH, text_color=COLOR_ACCENT)

    draw_wrapped(draw, lines, CONTENT_MARGIN_X, title_top, line_height, align="left", font_normal=fonts["title"])

    return bg.convert("RGB")


def render_body_card(card: dict, fonts: dict) -> Image.Image:
    """2~N번 카드(슬라이드 본문) 템플릿: 역할 태그 → (있으면) 요약 제목 박스 →
    (있으면) 포인트 칩 → 본문 문단 순으로 왼쪽 정렬로 쌓는다. 본문은 항상
    하단 고정이고, 위쪽 요소(요약 제목/포인트)가 유난히 길어서 겹칠 것 같으면
    본문을 그 아래로 내려서 배치한다.

    "요약 제목"은 본문 문장을 그대로 잘라 위로 올리는 게 아니라(문장이 중간에
    끊겨 보이는 문제가 있었음) Claude가 새로 뽑은 짧은 문구를 쓴다 —
    annotate_cards()가 없으면(ANTHROPIC_API_KEY 미설정 등) heading/point 없이
    본문만 렌더링된다."""
    heading = card.get("heading")
    point = card.get("point")
    body_text = card.get("annotated_text") or card["text"]

    body_lines = wrap_tokens(body_text, fonts["body"], CONTENT_WIDTH)
    body_line_height = int(BODY_SIZE * 1.5)
    body_block_height = body_line_height * len(body_lines)

    # 1) 위쪽 블록(요약 제목 + 포인트 칩)이 실제로 몇 픽셀을 차지하는지 더미
    # draw로 먼저 계산한다 — 이걸 알아야 본문이 겹치지 않는 위치를 알 수 있고,
    # 스크림도 최종 본문 위치에 맞춰 미리 깔 수 있다.
    y = SAFE_TOP + TAG_RESERVE
    if heading:
        y = render_box_text(_MEASURE_DRAW, heading, CONTENT_MARGIN_X, y, fonts["heading"], CONTENT_WIDTH)
    if point:
        y = render_box_text(_MEASURE_DRAW, point, CONTENT_MARGIN_X, y, fonts["point"], CONTENT_WIDTH, prefix="→ ", outline=COLOR_ACCENT)
    top_block_bottom = y

    body_top = SAFE_BOTTOM - body_block_height
    if body_top < top_block_bottom:
        body_top = top_block_bottom  # 부득이하게 겹치면 위쪽 블록 바로 아래로

    bg = load_background(card.get("local_path"))
    bg = add_scrim(bg, bands=[(body_top - 44, CANVAS_H, 200)])
    draw = ImageDraw.Draw(bg)

    draw_role_tag(draw, card["role"], fonts)

    y = SAFE_TOP + TAG_RESERVE
    if heading:
        y = render_box_text(draw, heading, CONTENT_MARGIN_X, y, fonts["heading"], CONTENT_WIDTH)
    if point:
        y = render_box_text(draw, point, CONTENT_MARGIN_X, y, fonts["point"], CONTENT_WIDTH, prefix="→ ", outline=COLOR_ACCENT)

    draw_wrapped(
        draw, body_lines, CONTENT_MARGIN_X, body_top, body_line_height,
        align="left", font_normal=fonts["body"], font_accent=fonts["body_bold"],
    )

    return bg.convert("RGB")


def render_closing_card(card: dict, fonts: dict) -> Image.Image:
    """마지막 카드(마무리) 템플릿: CTA + 댓글 유도 질문 + 계정 핸들을 왼쪽
    정렬로 배치한다. approved_script.json의 cta/comment_question은 어느
    슬라이드에도 안 묶여 있어서, 마지막 슬라이드 이미지를 재사용해 이 카드를
    새로 만든다."""
    bg = load_background(card.get("local_path"))
    bg = add_full_scrim(bg, opacity=165)
    draw = ImageDraw.Draw(bg)

    draw_role_tag(draw, "마무리", fonts)

    cta_lines = wrap_tokens(card["cta"], fonts["title"], CONTENT_WIDTH)
    cta_line_height = int(TITLE_SIZE * 1.25)
    y = int(CANVAS_H * 0.40)
    y = draw_wrapped(draw, cta_lines, CONTENT_MARGIN_X, y, cta_line_height, align="left", font_normal=fonts["title"], fill_normal=COLOR_ACCENT)

    y += 30
    q_lines = wrap_tokens(card["comment_question"], fonts["body"], CONTENT_WIDTH)
    q_line_height = int(BODY_SIZE * 1.35)
    draw_wrapped(draw, q_lines, CONTENT_MARGIN_X, y, q_line_height, align="left", font_normal=fonts["body"])

    draw.text((CONTENT_MARGIN_X, SAFE_BOTTOM - LABEL_SIZE), ACCOUNT_HANDLE, font=fonts["label"], fill=COLOR_TEXT)

    return bg.convert("RGB")


# ---------------------------------------------------------------------------
# 파이프라인
# ---------------------------------------------------------------------------

def safe_filename(text: str, max_len: int = 12) -> str:
    keep = "".join(c for c in text if c.isalnum())
    return keep[:max_len] if keep else "card"


def build_cards(script: dict, manifest: list, annotations: dict = None) -> list:
    """crop_manifest.json의 각 카드(표지+슬라이드) + approved_script.json에서
    뽑은 마무리 카드까지 합쳐서 렌더링 대상 목록을 만든다. annotations는
    annotate_cards()가 만든 {index: {heading, annotated_text, point}} 맵."""
    annotations = annotations or {}
    fonts = load_fonts()

    results = []
    for card in manifest:
        card = {**card, "topic": script.get("topic", ""), **annotations.get(card["index"], {})}
        if card["role"] == "표지":
            img = render_header_card(card, fonts)
        else:
            img = render_body_card(card, fonts)
        results.append((card["index"], card["role"], img))
        print(f"  카드 {card['index']}({card['role']}) 렌더링 완료")

    last_with_image = next((c for c in reversed(manifest) if c.get("local_path")), None)
    closing_card = {
        "local_path": last_with_image.get("local_path") if last_with_image else None,
        "cta": script.get("cta", ""),
        "comment_question": script.get("comment_question", ""),
    }
    closing_img = render_closing_card(closing_card, fonts)
    closing_index = (manifest[-1]["index"] + 1) if manifest else 1
    results.append((closing_index, "마무리", closing_img))
    print(f"  카드 {closing_index}(마무리) 렌더링 완료")

    return results


def main():
    manifest_path = PROJECT_DIR / "crop_manifest.json"
    script_path = PROJECT_DIR / "approved_script.json"
    if not manifest_path.exists():
        raise SystemExit(f"{manifest_path} 이 없습니다. 먼저 crop_images.py를 실행하세요.")
    if not script_path.exists():
        raise SystemExit(f"{script_path} 이 없습니다. 먼저 orchestrator.py를 실행하세요.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    script = json.loads(script_path.read_text(encoding="utf-8"))

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
