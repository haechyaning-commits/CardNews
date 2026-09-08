"""
디자이너(Designer) 에이전트

crop_images.py가 만들어둔 로컬 이미지(crop_manifest.json + images/, 이미 1080x1350
4:5로 크롭되고 톤 보정까지 끝난 상태)에 작가가 쓴 문구를 얹어서 실제 인스타그램에
올릴 최종 카드뉴스 PNG를 만든다. Skill 문서 3번(디자이너 규칙)을 코드로 강제한다:

- 전체 슬라이드 4:5(1080x1350) 고정 — crop_images.py가 이미 보장하므로 여기선 그대로 사용.
- 템플릿 3종 고정: 헤더(표지) / 본문(슬라이드) / 마무리(CTA+댓글유도+핸들).
- 폰트 최대 2종(제목 1개 + 본문 1개, 굵기로 위계). 색상은 흰 텍스트 / 포인트색 /
  어두운 스크림(반투명 박스 역할) 3가지로 고정.
- 사진 위에 얹는 텍스트는 항상 어두운 그라데이션 스크림 뒤에 놓아서, 사진이
  밝든 어둡든 가독성이 항상 확보되게 한다.
- 상하 15%는 프로필 아이콘/캡션 UI에 가려질 수 있는 세이프존이라 핵심 텍스트는
  그 안쪽에 배치한다.

approved_script.json에는 슬라이드(표지+2~8번)와 별개로 cta/comment_question이
최상위 필드로 따로 있다(어느 슬라이드에도 안 묶여 있음) — 이건 "마무리" 카드가
아직 없어서다. 그래서 여기서 마지막 슬라이드 이미지를 재사용한 "마무리" 카드를
하나 더 만들어서 cta+comment_question+계정 핸들을 얹는다. 이렇게 하면 슬라이드
총 장수(원래 8장 + 마무리 1장 = 9장)도 Skill의 "7~10장" 범위 안에 그대로 들어간다.

키워드 강조(**단어**) 지원: Skill 3번은 "작가가 표시해둔 핵심 키워드는 볼드/포인트
색상으로 강조 처리한다"고 하는데, writer_agent.py는 아직 이런 마크업을 만들지
않는다(대본에 **가 없으면 전부 기본 스타일로만 렌더링됨). 나중에 작가 에이전트가
**키워드** 형태로 표시하기 시작하면 이 파일은 코드 변경 없이 바로 포인트 색상으로
강조해준다 — 지금은 미리 준비만 해둔 상태.

폰트: 한글이 보이는 TTF/OTF가 필요하다. 아래 순서로 자동 탐색한다.
1. FONT_REGULAR_PATH / FONT_BOLD_PATH 환경변수로 직접 지정한 경로
2. 프로젝트 폴더의 fonts/NotoSansKR-Regular.otf / fonts/NotoSansKR-Bold.otf
   (무료 다운로드: https://fonts.google.com/noto/specimen/Noto+Sans+KR)
3. macOS/Windows/Linux에 흔히 이미 깔려있는 한글 폰트(맑은 고딕, Apple SD 산돌고딕,
   나눔고딕, Noto Sans CJK 등)
아무것도 못 찾으면 실행을 멈추고 fonts/ 폴더에 폰트를 넣으라고 안내한다.

사용법
------
1. pip install Pillow
2. crop_manifest.json + images/ 가 폴더에 있어야 한다 (먼저 crop_images.py 실행).
3. (필요하면) export ACCOUNT_HANDLE="@계정핸들" — 마무리 카드 하단에 표시된다.
   안 정하면 "@계정핸들"이 자리표시자로 들어가니 실제 발행 전에 바꿔야 한다.
4. python designer_agent.py

결과: final/ 폴더에 card_01_표지.png ~ card_09_마무리.png 로 저장되고,
각 카드의 최종 경로/역할이 담긴 final_manifest.json도 같이 생성된다.
"""

import json
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_DIR = Path(__file__).parent

CANVAS_W, CANVAS_H = 1080, 1350

# 상하 15%는 인스타 UI(프로필 아이콘, 캡션 등)에 가려질 수 있는 세이프존.
# 핵심 텍스트는 이 안쪽(SAFE_TOP ~ SAFE_BOTTOM)에만 배치한다.
SAFE_TOP = int(CANVAS_H * 0.15)
SAFE_BOTTOM = CANVAS_H - int(CANVAS_H * 0.15)
CONTENT_MARGIN_X = 72  # 좌우 여백
CONTENT_WIDTH = CANVAS_W - CONTENT_MARGIN_X * 2

# 색상 팔레트: 텍스트(흰색) / 포인트(웜 톤 포인트색) / 스크림(검정, 아래 텍스트
# 뒤에 까는 반투명 박스 역할) 3가지로 고정한다. 포인트색은 crop_images.py의
# 계정 고유 웜+뮤트 필터(붉은기를 살짝 올리는 방향)와 톤을 맞춰서 시리즈 전체가
# 하나의 색 느낌으로 보이게 골랐다.
COLOR_TEXT = (255, 255, 255, 255)
COLOR_ACCENT = (232, 176, 132, 255)
COLOR_SCRIM = (20, 15, 12)

TITLE_SIZE = 72   # 표지 hook / 마무리 CTA — 최소 32pt 상당 요구 대비 넉넉하게
BODY_SIZE = 48    # 슬라이드 본문 — 최소 24pt 상당 요구 대비 넉넉하게
LABEL_SIZE = 30   # 역할 태그 / 페이지 인디케이터 / 계정 핸들 / 작은 보조문구

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
    """제목용/본문용/보조용 폰트를 각각 3가지 크기로 미리 만들어둔다.
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
        "body": make(reg_path, reg_idx, BODY_SIZE),
        "body_bold": make(bold_path, bold_idx, BODY_SIZE),
        "label": make(bold_path, bold_idx, LABEL_SIZE),
        "label_regular": make(reg_path, reg_idx, LABEL_SIZE),
    }


# ---------------------------------------------------------------------------
# 텍스트 줄바꿈 + **키워드** 강조 마크업
# ---------------------------------------------------------------------------

# 줄바꿈 계산(wrap_tokens)은 실제 이미지 픽셀과 무관하게 폰트 메트릭만 있으면
# 되므로, 매 카드 이미지를 만들기 전에 이 더미 draw로 먼저 계산해서 텍스트가
# 몇 줄인지/블록 높이가 얼마인지 알아낸다. 이걸 알아야 스크림(어두운 그라데이션)을
# "텍스트가 시작되는 지점"에 맞춰 깔 수 있다 — 순서를 반대로(이미지부터 만들고
# 고정된 비율로 스크림을 깐 다음 텍스트를 얹으면) 슬라이드마다 문구 길이가
# 달라서 어떤 카드는 스크림이 옅은 지점에 첫 줄이 걸려 가독성이 떨어지는 문제가
# 있었다.
_MEASURE_DRAW = ImageDraw.Draw(Image.new("RGB", (10, 10)))

_ACCENT_RE = re.compile(r"\*\*(.+?)\*\*")


def _tokenize(text: str) -> list:
    """"**중요** 단어" 같은 문자열을 [(word, is_accent), ...] 형태로 분해한다.
    ** 로 감싼 부분은 공백 기준으로 쪼개도 전부 is_accent=True를 유지한다."""
    tokens = []
    pos = 0
    for m in _ACCENT_RE.finditer(text):
        before = text[pos:m.start()]
        for w in before.split():
            tokens.append((w, False))
        for w in m.group(1).split():
            tokens.append((w, True))
        pos = m.end()
    for w in text[pos:].split():
        tokens.append((w, False))
    return tokens


def wrap_tokens(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    """단어(토큰) 단위로 max_width 안에 들어가게 줄바꿈한다. 한 단어가 그
    자체로 max_width보다 길면(거의 없지만 안전장치로) 글자 단위로 쪼갠다.
    폰트 메트릭만 있으면 계산되므로 실제 카드 이미지가 아직 없어도(스크림
    범위를 정하기 전에도) 미리 호출할 수 있다 — 모듈 상단의 _MEASURE_DRAW를 씀."""
    draw = _MEASURE_DRAW
    space_w = draw.textlength(" ", font=font)
    lines, current, current_w = [], [], 0.0

    def flush():
        if current:
            lines.append(list(current))
            current.clear()

    for word, accent in _tokenize(text):
        w = draw.textlength(word, font=font)
        if w > max_width:
            # 단어 하나가 통째로 너무 길면 글자 단위로 쪼개서 강제로 줄바꿈한다.
            flush()
            chunk = ""
            for ch in word:
                if draw.textlength(chunk + ch, font=font) > max_width and chunk:
                    lines.append([(chunk, accent)])
                    chunk = ch
                else:
                    chunk += ch
            if chunk:
                current.append((chunk, accent))
                current_w = draw.textlength(chunk, font=font)
            continue

        added_w = w if not current else current_w + space_w + w
        if added_w > max_width and current:
            flush()
            current_w = 0.0
            added_w = w
        current.append((word, accent))
        current_w = added_w

    flush()
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    lines: list,
    font: ImageFont.FreeTypeFont,
    center_x: int,
    top_y: int,
    line_height: int,
    fill_normal=COLOR_TEXT,
    fill_accent=COLOR_ACCENT,
) -> int:
    """wrap_tokens()가 만든 줄들을 가운데 정렬로 그리고, 마지막 줄 다음 y좌표를
    반환한다(다음 텍스트 블록을 이어붙일 때 씀)."""
    space_w = draw.textlength(" ", font=font)
    y = top_y
    for line in lines:
        line_w = sum(draw.textlength(w, font=font) for w, _ in line) + space_w * max(0, len(line) - 1)
        x = center_x - line_w / 2
        for word, accent in line:
            draw.text((x, y), word, font=font, fill=fill_accent if accent else fill_normal)
            x += draw.textlength(word, font=font) + space_w
        y += line_height
    return y


# ---------------------------------------------------------------------------
# 배경(사진 또는 대체 배경) + 스크림
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


def add_scrim(img: Image.Image, dark_from_y: int, max_opacity: int, fade_height: int = 160, min_opacity: int = 40) -> Image.Image:
    """dark_from_y 지점부터는 max_opacity로 완전히 어둡고, 그 위 fade_height
    구간은 min_opacity에서 max_opacity로 서서히 어두워지고, 그보다 더 위는
    min_opacity로 은은하게 깔린다(맨 위 역할 태그도 밝은 사진 위에서 살짝은
    또렷해지게).

    dark_from_y를 텍스트 블록이 시작되는 y좌표로 넘기면, 문구가 몇 줄이든
    상관없이 텍스트 전체가 항상 max_opacity 스크림 위에 놓인다 — 예전엔 이미지
    하단 비율(예: 50%)로 고정해서 깔았는데, 슬라이드마다 문구 길이가 달라
    문구가 긴 카드는 첫 줄이 스크림이 옅은 지점에 걸려 밝은 사진에서 가독성이
    떨어지는 문제가 있었다."""
    w, h = img.size
    fade_start = max(0, dark_from_y - fade_height)
    gradient = Image.new("L", (1, h), 0)
    for y in range(h):
        if y >= dark_from_y:
            v = max_opacity
        elif y <= fade_start:
            v = min_opacity
        else:
            t = (y - fade_start) / max(1, dark_from_y - fade_start)
            v = int(min_opacity + (max_opacity - min_opacity) * t)
        gradient.putpixel((0, y), v)
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


# ---------------------------------------------------------------------------
# 3종 템플릿
# ---------------------------------------------------------------------------

def draw_role_tag(draw, label: str, page_note: str, fonts: dict):
    """세이프존 위쪽에 역할 태그(작은 포인트색 글씨)와 페이지 인디케이터를
    한 줄에 배치한다. 모든 본문/표지 카드가 공유하는 공통 요소.

    이 영역은 하단 스크림이 안 닿는 곳이라 사진이 밝으면 글씨가 묻힐 수
    있어서, 텍스트마다 작은 반투명 박스를 뒤에 깔아 사진 밝기와 무관하게
    항상 읽히게 한다."""
    y = SAFE_TOP
    pad_x, pad_y = 16, 10

    def pill(x0, x1):
        draw.rounded_rectangle([x0 - pad_x, y - pad_y, x1 + pad_x, y + LABEL_SIZE + pad_y], radius=8, fill=(*COLOR_SCRIM, 140))

    label_w = draw.textlength(label, font=fonts["label"])
    pill(CONTENT_MARGIN_X, CONTENT_MARGIN_X + label_w)
    draw.text((CONTENT_MARGIN_X, y), label, font=fonts["label"], fill=COLOR_ACCENT)

    note_w = draw.textlength(page_note, font=fonts["label_regular"])
    note_x = CANVAS_W - CONTENT_MARGIN_X - note_w
    pill(note_x, note_x + note_w)
    draw.text((note_x, y), page_note, font=fonts["label_regular"], fill=COLOR_TEXT)


def render_header_card(card: dict, fonts: dict, total: int) -> Image.Image:
    """1번 카드(표지) 템플릿: 톤/주제 키워드를 작은 라벨로 위에 깔고, hook
    문구를 큼직하게 하단 세이프존에 배치한다. 캡션/해시태그와 마찬가지로
    이미지 안에도 주제 키워드가 자연스럽게 들어가게 하는 효과도 있다."""
    lines = wrap_tokens(card["text"], fonts["title"], CONTENT_WIDTH)
    line_height = int(TITLE_SIZE * 1.35)
    top_y = SAFE_BOTTOM - line_height * len(lines)

    bg = load_background(card.get("local_path"))
    bg = add_scrim(bg, dark_from_y=top_y, max_opacity=205)
    draw = ImageDraw.Draw(bg)

    draw_role_tag(draw, "표지", f"1/{total}", fonts)

    topic = card.get("topic", "")
    if topic:
        topic_y = SAFE_TOP + 60
        topic_w = draw.textlength(topic, font=fonts["label_regular"])
        draw.rounded_rectangle(
            [CONTENT_MARGIN_X - 16, topic_y - 10, CONTENT_MARGIN_X + topic_w + 16, topic_y + LABEL_SIZE + 10],
            radius=8,
            fill=(*COLOR_SCRIM, 140),
        )
        draw.text((CONTENT_MARGIN_X, topic_y), topic, font=fonts["label_regular"], fill=COLOR_ACCENT)

    draw_wrapped(draw, lines, fonts["title"], CANVAS_W // 2, top_y, line_height)

    return bg.convert("RGB")


def render_body_card(card: dict, fonts: dict, total: int) -> Image.Image:
    """2~N번 카드(슬라이드 본문) 템플릿: 역할 태그(배경설명/핵심정보/반전인사이트
    등) + 슬라이드 문구를 하단 세이프존에 배치한다."""
    lines = wrap_tokens(card["text"], fonts["body_bold"], CONTENT_WIDTH)
    line_height = int(BODY_SIZE * 1.4)
    top_y = SAFE_BOTTOM - line_height * len(lines)

    bg = load_background(card.get("local_path"))
    bg = add_scrim(bg, dark_from_y=top_y, max_opacity=200)
    draw = ImageDraw.Draw(bg)

    draw_role_tag(draw, card["role"], f"{card['page']}/{total}", fonts)
    draw_wrapped(draw, lines, fonts["body_bold"], CANVAS_W // 2, top_y, line_height)

    return bg.convert("RGB")


def render_closing_card(card: dict, fonts: dict, total: int) -> Image.Image:
    """마지막 카드(마무리) 템플릿: CTA + 댓글 유도 질문 + 계정 핸들을 배치한다.
    approved_script.json의 cta/comment_question은 어느 슬라이드에도 안 묶여
    있어서, 마지막 슬라이드 이미지를 재사용해 이 카드를 새로 만든다."""
    bg = load_background(card.get("local_path"))
    bg = add_full_scrim(bg, opacity=165)
    draw = ImageDraw.Draw(bg)

    draw_role_tag(draw, "마무리", f"{total}/{total}", fonts)

    cta_lines = wrap_tokens(card["cta"], fonts["title"], CONTENT_WIDTH)
    cta_line_height = int(TITLE_SIZE * 1.3)
    y = int(CANVAS_H * 0.42)
    y = draw_wrapped(draw, cta_lines, fonts["title"], CANVAS_W // 2, y, cta_line_height, fill_accent=COLOR_ACCENT)

    y += 24
    q_lines = wrap_tokens(card["comment_question"], fonts["body"], CONTENT_WIDTH)
    q_line_height = int(BODY_SIZE * 1.35)
    draw_wrapped(draw, q_lines, fonts["body"], CANVAS_W // 2, y, q_line_height)

    handle_w = draw.textlength(ACCOUNT_HANDLE, font=fonts["label"])
    draw.text(
        ((CANVAS_W - handle_w) / 2, SAFE_BOTTOM - LABEL_SIZE),
        ACCOUNT_HANDLE,
        font=fonts["label"],
        fill=COLOR_TEXT,
    )

    return bg.convert("RGB")


# ---------------------------------------------------------------------------
# 파이프라인
# ---------------------------------------------------------------------------

def safe_filename(text: str, max_len: int = 12) -> str:
    keep = "".join(c for c in text if c.isalnum())
    return keep[:max_len] if keep else "card"


def build_cards(script: dict, manifest: list) -> list:
    """crop_manifest.json의 각 카드(표지+슬라이드) + approved_script.json에서
    뽑은 마무리 카드까지 합쳐서 렌더링 대상 목록을 만든다."""
    fonts = load_fonts()
    total = len(manifest) + 1  # 슬라이드 전부 + 마무리 카드 1장

    results = []
    for i, card in enumerate(manifest, start=1):
        card = {**card, "page": i, "topic": script.get("topic", "")}
        if card["role"] == "표지":
            img = render_header_card(card, fonts, total)
        else:
            img = render_body_card(card, fonts, total)
        results.append((card["index"], card["role"], img))
        print(f"  카드 {card['index']}({card['role']}) 렌더링 완료")

    last_with_image = next((c for c in reversed(manifest) if c.get("local_path")), None)
    closing_card = {
        "local_path": last_with_image.get("local_path") if last_with_image else None,
        "cta": script.get("cta", ""),
        "comment_question": script.get("comment_question", ""),
    }
    closing_img = render_closing_card(closing_card, fonts, total)
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

    print(f"'{script.get('topic', '')}' 카드뉴스 최종 이미지를 만듭니다...\n")
    cards = build_cards(script, manifest)

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
