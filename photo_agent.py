"""
사진수집가(Photo Collector) 에이전트

approved_script.json(작가+PM 통과본)을 읽어서 카드(표지+슬라이드)마다
어울리는 이미지를 Unsplash + Pexels에서 찾아 배정한다. Skill 문서 4번
(사진수집가 규칙)에 따라 라이선스 프리 소스만 쓰고, 전후비교 느낌의
이미지는 피하도록 한다.

왜 두 소스를 같이 쓰나: Unsplash 하나만 쓰면 사진 풀 자체가 서구권 모델/
사진작가 위주로 치우쳐 있어서, 검색어를 아무리 잘 만들어도 "한국 20대
라이프스타일" 느낌을 찾기 어려운 경우가 있었다. Pexels를 추가해서 후보
풀을 넓히면 그만큼 원하는 느낌에 맞는 사진을 찾을 확률이 올라간다.
PEXELS_API_KEY가 없으면 Unsplash만으로 동작한다 (필수 아님, 있으면 더 좋음).

동작 순서
--------
0. 카드 하나하나를 보기 전에, 대본 전체(주제/표지 문구)를 보고 이번 세트에
   통일해서 쓸 톤(밝고 화사한/따뜻한/깨끗한 미니멀/차분한 뮤트 중 하나)을 딱
   한 번만 정한다. 이후 모든 카드가 이 톤을 기준으로 검색·선택된다 — 다
   고르고 나서 밝기를 맞추는 게 아니라, 애초에 통일된 톤의 사진만 고르는
   방식이다.
1. 카드마다 Claude가 검색어(영어)를 만든다. 이때 0번에서 정한 톤에 맞는
   조명/분위기 키워드를 검색어에 함께 넣는다.
2. Unsplash와 Pexels(있으면) 양쪽에서 후보를 가져와 하나로 합친 뒤,
   가로세로비(4:5 근접도)와 대표색으로 추정한 밝기가 0번 목표 밝기에
   가까운 순서로 정렬해서 상위 5개만 후보로 남긴다.
3. Claude가 후보 설명을 보고 카드 내용에 가장 잘 맞으면서 톤도 맞는 걸 고른다.
4. 실제로 쓰기로 한 이미지가 Unsplash 사진이면, Unsplash 가이드라인에 따라
   download_location에 요청을 보내 다운로드로 집계되게 한다 (사진작가에게
   크레딧이 가는 절차). Pexels는 이런 별도 집계 절차가 없다.
5. 결과(이미지 URL, 출처, 저작자 이름/프로필, alt 텍스트, 이번에 정한 톤)를
   photo_assignments.json으로 저장한다. 이 파일이 다음 단계(디자이너
   에이전트)의 입력이 된다. crop_images.py에서 하는 밝기/색감 보정은 이
   단계에서 이미 톤을 맞춰 고른 사진들을 마지막으로 한 번 더 다듬는 보조
   장치로 남겨둔다.

주의: 이미지 파일 자체를 영구 보관 목적으로 다운로드하지 않고 각 사이트가
제공하는 URL을 그대로 쓴다 — Unsplash API 가이드라인상 이미지를 직접
다운로드해 자체 서버에 영구 보관하는 것은 권장되지 않는다.

사용법
------
1. unsplash.com/oauth/applications 에서 무료로 앱을 등록하고 Access Key를
   발급받아 환경변수로 설정한다.
       export UNSPLASH_ACCESS_KEY="여기에-발급받은-키"
   (초기엔 시간당 50 요청 제한인데, 카드 한 세트에 8번 정도만 쓰니 충분하다)
2. (선택, 권장) pexels.com/api 에서 무료로 API 키를 즉시 발급받아 설정한다.
       export PEXELS_API_KEY="여기에-발급받은-키"
   (Pexels는 즉시 발급, 시간당 200 요청 제한이라 Unsplash보다 여유롭다)
3. ANTHROPIC_API_KEY도 그대로 설정되어 있어야 한다.
4. approved_script.json이 폴더에 있어야 한다 (먼저 orchestrator.py 실행).
5. python photo_agent.py
"""

import base64
import json
import os
from pathlib import Path

import anthropic
import requests

MODEL = "claude-sonnet-5"
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


TARGET_RATIO = 1080 / 1350  # 인스타 캐러셀 권장 비율 4:5 = 0.8

# Unsplash 데모 앱은 시간당 50 요청 제한이 있다. 같은 세트를 여러 번 테스트하다
# 보면(특히 재시도 라운드까지 있으면 세트당 요청이 8~16개) 금방 넘길 수 있는데,
# 이럴 때 403이 뜬다. 한 번 403을 만나면 이번 실행 내내 Unsplash 재요청을
# 멈추고 Pexels로만 진행해서, 카드마다 똑같은 403 에러로 멈추는 걸 막는다.
_unsplash_rate_limited = False

# 같은 인물/사진작가가 세트를 새로 만들 때마다 계속 등장하는 걸 막기 위한
# 영구 차단 목록. photo_agent.py 안에서는 읽기만 하고, 실제로 항목을 추가하는
# 건 ban_photo.py 스크립트가 한다 (예: python3 ban_photo.py photographer "이름").
BANNED_PATH = Path(__file__).parent / "banned_photos.json"

# 인물이 나오는 구도(close_up_face, half_body_portrait)가 이 횟수만큼 연속으로
# 나오면, 그 다음 카드는 무조건 인물 없는 구도(손/제품/일상)만 고르도록 강제한다.
# "웬만하면 다른 구도로" 같은 프롬프트 지시만으로는 4카드 연속 인물샷이 나오는 걸
# 못 막았어서, 선택지 자체를 코드로 좁히는 방식으로 바꿨다.
MAX_CONSECUTIVE_PERSON_SHOTS = 2


def load_banned() -> dict:
    """banned_photos.json이 있으면 읽어서 {"photographers": [...], "photo_ids": [...]}
    형태로 반환한다. 파일이 없거나 깨져 있으면 빈 목록으로 안전하게 넘어간다."""
    if BANNED_PATH.exists():
        try:
            data = json.loads(BANNED_PATH.read_text(encoding="utf-8"))
            return {
                "photographers": data.get("photographers", []),
                "photo_ids": data.get("photo_ids", []),
            }
        except Exception as e:
            print(f"(banned_photos.json을 읽는 데 실패해서 무시하고 진행해요: {e})")
    return {"photographers": [], "photo_ids": []}

# 카드마다 사진 구도가 다 "얼굴 클로즈업"으로 겹치면 세트 전체가 단조롭고
# 붕어빵처럼 보인다. 검색어를 만들 때 이 구도들 중 하나를 매번 고르게 강제해서
# 카드 간 시각적 리듬을 준다.
#
# texture_detail(피부/제품 질감 클로즈업)은 원래 있었는데 뺐다 — alt_description
# 텍스트만 보고 고르다 보니 "종이 질감", "패브릭 주름" 같은 스킨케어와 전혀
# 상관없는 추상적인 사진을 "은유적으로 어울린다"고 억지로 골라오는 경우가
# 많았다(실제로 카드 2/4/7에서 이 문제가 나왔음). 실물이 뭔지 명확한 구도만
# 남겨서, 카드 내용과 진짜 상관있는 사진만 고르게 한다.
SHOT_TYPES = [
    "close_up_face",       # 얼굴 클로즈업
    "half_body_portrait",  # 상반신/어깨 위 인물샷
    "hands_action",        # 손으로 제품 바르거나 만지는 장면
    "product_flatlay",     # 제품/화장대 위 정물
    "lifestyle_scene",     # 일상 속 장면 (거울 앞, 화장실 등)
]

# Unsplash는 미국/유럽 사진작가 비중이 높아서 기본 검색어로는 서구권 모델
# 사진이 압도적으로 많이 나온다. 인물이 나오는 구도(얼굴/상반신)에는 "asian"을
# 붙여서 그나마 동양인 모델 사진이 더 잡히게 한다. 다만 Unsplash에 "한국인"만
# 콕 집어 찾을 만큼 데이터가 많지는 않아서 완벽한 해결책은 아니다 — 그래서
# 아예 인물이 안 나오는 구도(손/제품/질감)도 절반 가까이 섞어서, 인물 사진의
# "외국인 느낌"이 세트 전체 인상을 좌우하지 않게 하는 쪽으로 같이 대응한다.
PERSON_SHOT_TYPES = {"close_up_face", "half_body_portrait"}

# hands_action/product_flatlay는 "인물이 안 나오는 구도"로 분류해뒀지만,
# 실제로 돌려보니 "손으로 크림 바르는" 같은 검색어의 상당수 결과가 얼굴을
# 같이 프레이밍하고 있어서(스톡 사진 특성상 아주 흔함) close_up_face/
# half_body_portrait 사진과 시각적으로 거의 구분이 안 되는 문제가 있었다
# ("사진이 다 비슷한 얼굴 클로즈업으로 보인다"는 피드백). 프롬프트로
# "인물이 안 나오니 신경 안 써도 된다"고만 해둔 게 원인이라, 검색어 자체에
# 얼굴을 배제하는 키워드를 코드로 강제로 덧붙인다.
NO_FACE_QUERY_SUFFIX = {
    "hands_action": "hands only cropped no face",
    "product_flatlay": "no person no face",
}

# 카드마다 사진을 따로따로 고른 뒤 나중에 밝기를 맞추는 게 아니라, 애초에
# "이번 세트는 이 톤으로 간다"를 먼저 정하고 그 톤에 맞는 사진만 검색·선택
# 하기 위한 프리셋. search_hint는 검색어에 곁들일 영어 키워드, target_brightness는
# Unsplash가 사진마다 제공하는 대표색(color)으로 추정한 밝기(0~255)의 목표값이다.
TONE_PRESETS = {
    "bright_natural": {
        "search_hint": "bright natural light",
        "target_brightness": 190,
        "kr_label": "밝고 화사한 내추럴톤",
    },
    "warm_soft": {
        "search_hint": "warm soft light",
        "target_brightness": 165,
        "kr_label": "따뜻하고 부드러운 웜톤",
    },
    "clean_minimal": {
        "search_hint": "clean minimal white",
        "target_brightness": 205,
        "kr_label": "깨끗한 화이트 미니멀톤",
    },
    "muted_calm": {
        "search_hint": "muted calm soft",
        "target_brightness": 150,
        "kr_label": "차분한 뮤트톤",
    },
}


def hex_to_brightness(hex_color: str):
    """Unsplash 후보 사진의 대표색(예: '#c0a080')으로 대략적인 밝기(0~255)를
    추정한다. crop_images.py가 실제 픽셀로 계산하는 것과 같은 가중치(ITU-R 601)
    를 써서, 나중에 크롭 단계의 밝기 값과 같은 기준으로 비교할 수 있게 한다."""
    if not hex_color:
        return None
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return None
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    except ValueError:
        return None
    return r * 0.299 + g * 0.587 + b * 0.114


def _normalize_unsplash(raw: dict) -> dict:
    """Unsplash API가 주는 원본 JSON을 두 소스(Unsplash/Pexels) 공통 형식으로
    바꾼다. 이후 코드(랭킹, pick_best, 최종 저장)는 소스가 뭐든 이 공통 형식만
    보면 되니 소스별 분기를 여기 한 곳에만 몰아둔다."""
    return {
        "source": "unsplash",
        "source_label": "Unsplash",
        "id": f"unsplash_{raw['id']}",
        "width": raw["width"],
        "height": raw["height"],
        "color": raw.get("color"),
        "alt_description": raw.get("alt_description") or raw.get("description") or "",
        "url_thumb": raw["urls"].get("small") or raw["urls"].get("thumb") or raw["urls"]["regular"],
        "url_regular": raw["urls"]["regular"],
        "url_full": raw["urls"]["full"],
        "download_location": raw["links"]["download_location"],
        "photographer": raw["user"]["name"],
        "photographer_profile": raw["user"]["links"]["html"],
        "likes": raw.get("likes", 0),
    }


def _normalize_pexels(raw: dict) -> dict:
    """Pexels API가 주는 원본 JSON을 공통 형식으로 바꾼다. Pexels는
    download_location 같은 별도 집계 절차가 없어서 None으로 둔다."""
    src = raw.get("src", {})
    return {
        "source": "pexels",
        "source_label": "Pexels",
        "id": f"pexels_{raw['id']}",
        "width": raw["width"],
        "height": raw["height"],
        "color": raw.get("avg_color"),
        "alt_description": raw.get("alt") or "",
        "url_thumb": src.get("medium") or src.get("small") or src.get("large"),
        "url_regular": src.get("large2x") or src.get("large") or src.get("original"),
        "url_full": src.get("original") or src.get("large2x"),
        "download_location": None,
        "photographer": raw.get("photographer", ""),
        "photographer_profile": raw.get("photographer_url", ""),
        # Pexels 검색 API는 좋아요 수를 안 줘서 None. rank_candidates에서
        # None이면 감점 없이 중립으로 처리한다.
        "likes": None,
    }


def fetch_unsplash_candidates(query: str, access_key: str, per_page: int = 15) -> list:
    """Unsplash에서 검색만 하고 공통 형식으로 바꿔서 돌려준다. 필터링/정렬은
    rank_candidates()에서 두 소스를 합친 뒤 한 번에 한다."""
    resp = requests.get(
        UNSPLASH_SEARCH_URL,
        params={"query": query, "per_page": per_page, "orientation": "portrait"},
        headers={"Authorization": f"Client-ID {access_key}"},
        timeout=15,
    )
    resp.raise_for_status()
    return [_normalize_unsplash(r) for r in resp.json().get("results", [])]


def fetch_pexels_candidates(query: str, access_key: str, per_page: int = 15) -> list:
    """Pexels에서 검색만 하고 공통 형식으로 바꿔서 돌려준다."""
    resp = requests.get(
        PEXELS_SEARCH_URL,
        params={"query": query, "per_page": per_page, "orientation": "portrait"},
        headers={"Authorization": access_key},
        timeout=15,
    )
    resp.raise_for_status()
    return [_normalize_pexels(r) for r in resp.json().get("photos", [])]


# 좋아요 수가 이 미만이면 "검증이 덜 된 사진"으로 보고 약간 감점한다. 이 값
# 이상부터는 더 감점하지 않는다 — 좋아요 100개짜리와 10000개짜리를 억지로
# 차등 줄 필요는 없고, "너무 무명이라 아무도 안 본 사진"만 걸러내면 된다.
POPULARITY_FLOOR = 50
POPULARITY_PENALTY_WEIGHT = 0.2  # ratio_distance(0~0.5대)와 비슷한 크기로 맞춘 가중치


def rank_candidates(candidates: list, exclude_ids: set, target_brightness: float = None, top_n: int = 5) -> list:
    """이미 다른 카드에 쓴 사진(exclude_ids)은 빼고, 가로세로비(4:5 근접도)·
    대표색으로 추정한 밝기가 목표 밝기에 가까운 정도·좋아요 수(있으면)를 합쳐서
    점수를 매긴 뒤 상위 top_n개만 남긴다. 최종 정확히 1080x1350으로 자르는 건
    crop_images.py가 담당하므로 여기서는 '어느 후보가 더 낫냐'만 정한다.

    좋아요 수를 넣은 이유: "전문적인/화보st 느낌 vs 일반 스냅샷st 느낌"을 사람이
    매번 눈으로 보고 나서야 판단할 수 있는 문제였는데, Unsplash가 제공하는
    좋아요 수는 "이미 많은 사람이 괜찮다고 본 사진"이라는 걸 코드로 미리
    걸러낼 수 있는 신호다. 이걸 랭킹에 넣어두면 애초에 후보 풀 상위권에
    무명/저품질 사진이 덜 올라오게 돼서, 나중에 사람이 일일이 보고 차단
    목록에 추가해야 하는 일 자체가 줄어든다. (Pexels는 검색 API가 좋아요 수를
    안 줘서 해당 사진은 감점도 가점도 없이 중립으로 둔다.)"""
    candidates = [c for c in candidates if c["id"] not in exclude_ids]

    def ratio_distance(photo):
        ratio = photo["width"] / photo["height"]
        return abs(ratio - TARGET_RATIO)

    def popularity_penalty(photo):
        likes = photo.get("likes")
        if likes is None:
            return 0.0
        if likes >= POPULARITY_FLOOR:
            return 0.0
        return (1 - likes / POPULARITY_FLOOR) * POPULARITY_PENALTY_WEIGHT

    def combined_score(photo):
        score = ratio_distance(photo)
        if target_brightness is not None:
            brightness = hex_to_brightness(photo.get("color"))
            if brightness is not None:
                # 0~255 범위 차이를 0~1대로 눌러서 ratio_distance(보통 0~0.5대)와
                # 비슷한 크기로 맞춘 뒤 더한다.
                score += abs(brightness - target_brightness) / 255
        score += popularity_penalty(photo)
        return score

    candidates.sort(key=combined_score)
    return candidates[:top_n]


def _is_banned(photo: dict, banned: dict) -> bool:
    """이 후보가 영구 차단 목록(banned_photos.json)에 걸리는지 확인한다.
    사진작가 이름은 대소문자/공백 차이를 무시하고 부분 일치가 아닌 완전 일치로
    비교한다(너무 느슨하게 부분 일치로 걸면 엉뚱한 작가까지 같이 걸릴 수 있어서)."""
    if not banned:
        return False
    banned_photographers = {p.strip().lower() for p in banned.get("photographers", [])}
    banned_ids = set(banned.get("photo_ids", []))
    if photo["id"] in banned_ids:
        return True
    photographer = (photo.get("photographer") or "").strip().lower()
    return photographer in banned_photographers


def gather_candidates(
    query: str,
    unsplash_key: str,
    pexels_key: str,
    exclude_ids: set,
    target_brightness: float = None,
    banned: dict = None,
) -> list:
    """Unsplash + Pexels(있으면)에서 후보를 모아 하나의 풀로 합친 뒤 랭킹을
    매긴다. 소스를 하나만 쓸 때보다 후보 풀이 넓어져서, 원하는 톤/느낌에 맞는
    사진을 찾을 확률이 올라간다. 어느 한쪽이 실패해도(레이트리밋, 네트워크
    오류 등) 전체 실행이 죽지 않고 나머지 소스로 계속 진행한다.

    banned(banned_photos.json에서 읽은 값)에 걸리는 사진작가/사진 ID는 애초에
    후보 풀에서 빼버린다 — "이번 카드에서만 빼줘"가 아니라 "이 사람/이 사진은
    앞으로 어떤 세트를 만들어도 다시는 나오면 안 된다"는 요청이었어서, exclude_ids
    (이번 실행 안에서만 유효한 중복 방지용)와 별도로 파일 기반 영구 차단을 둔다."""
    global _unsplash_rate_limited

    pool = []
    if _unsplash_rate_limited:
        pass  # 이미 이번 실행에서 403을 봤으니 재요청으로 시간 낭비하지 않는다
    else:
        try:
            pool = fetch_unsplash_candidates(query, unsplash_key)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 403:
                _unsplash_rate_limited = True
                print(
                    "    (Unsplash가 403으로 거부했어요 — 데모 앱 시간당 50요청 제한을 넘긴 것 "
                    "같아요. 이번 실행은 남은 카드부터 Pexels만으로 진행할게요. 한 시간 뒤 다시 "
                    "시도하거나, unsplash.com/oauth/applications에서 Production 승인을 받으면 "
                    "제한이 풀려요.)"
                )
            else:
                print(f"    (Unsplash 검색 실패(HTTP {status}), 이번 카드는 Pexels만 사용: {e})")
        except requests.RequestException as e:
            print(f"    (Unsplash 검색 중 네트워크 오류, 이번 카드는 Pexels만 사용: {e})")

    if pexels_key:
        try:
            pool += fetch_pexels_candidates(query, pexels_key)
        except requests.RequestException as e:
            print(f"    (Pexels 검색 실패, 지금까지 모은 후보만 사용: {e})")

    if banned:
        before_count = len(pool)
        pool = [p for p in pool if not _is_banned(p, banned)]
        blocked = before_count - len(pool)
        if blocked:
            print(f"    (영구 차단 목록에 걸려서 후보 {blocked}개 제외)")

    return rank_candidates(pool, exclude_ids, target_brightness)


DECIDE_TONE_TOOL = {
    "name": "submit_tone",
    "description": "이번 카드뉴스 세트 전체 이미지에 통일해서 적용할 톤(분위기)을 하나 고른다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tone_preset": {
                "type": "string",
                "enum": list(TONE_PRESETS.keys()),
                "description": "이번 세트 전체에 적용할 톤 프리셋",
            },
            "reason": {"type": "string", "description": "이 톤을 고른 이유 (한 줄)"},
        },
        "required": ["tone_preset", "reason"],
    },
}


def decide_tone(client: anthropic.Anthropic, script: dict) -> dict:
    """카드 하나하나를 보기 전에, 대본 전체(주제/표지 문구)를 보고 이번 세트
    전체에 통일해서 쓸 톤을 딱 한 번만 정한다. 이후 모든 카드의 검색어·사진
    선택이 이 톤 하나를 기준으로 이루어져서, '나중에 밝기를 맞추는' 게 아니라
    '처음부터 통일된 톤의 사진만 고르는' 방식이 된다."""
    system_prompt = """당신은 스킨케어 카드뉴스의 전체 이미지 톤(분위기)을 정하는 역할입니다.
아래 네 가지 톤 중 이번 주제/표지 문구에 가장 잘 어울리는 하나를 고르세요.

- bright_natural: 밝고 화사한 내추럴톤. 수분/보습, 화사함을 강조하는 주제에 어울림.
- warm_soft: 따뜻하고 부드러운 웜톤. 친근하고 편안한 느낌을 강조하는 주제에 어울림.
- clean_minimal: 깨끗한 화이트 미니멀톤. 트러블/여드름처럼 청결함·신뢰감을 강조하는 주제에 어울림.
- muted_calm: 차분한 뮤트톤. 민감성 피부, 진정 케어처럼 차분함을 강조하는 주제에 어울림.

submit_tone 도구로만 응답하세요."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=system_prompt,
        tools=[DECIDE_TONE_TOOL],
        tool_choice={"type": "tool", "name": "submit_tone"},
        messages=[
            {
                "role": "user",
                "content": f"주제: {script.get('topic', '')}\n표지 문구: {script.get('hook', '')}",
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_tone":
            preset_key = block.input["tone_preset"]
            preset = TONE_PRESETS.get(preset_key, TONE_PRESETS["bright_natural"])
            return {"preset": preset_key, "reason": block.input["reason"], **preset}

    # 안전장치: 도구 호출을 못 받으면 기본 톤으로 진행한다.
    return {"preset": "bright_natural", "reason": "기본값 사용", **TONE_PRESETS["bright_natural"]}


QUERY_TOOL = {
    "name": "submit_query",
    "description": "이 카드에 어울리는 이미지를 찾기 위한 영어 검색어와 구도를 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "shot_type": {
                "type": "string",
                "enum": SHOT_TYPES,
                "description": "이 카드에 쓸 사진의 구도. 직전 카드들과 겹치지 않게 다양하게 고른다.",
            },
            "query": {"type": "string", "description": "Unsplash에서 검색할 영어 키워드 (2~4단어)"},
        },
        "required": ["shot_type", "query"],
    },
}


def generate_query(
    client: anthropic.Anthropic,
    card_text: str,
    role: str,
    recent_shot_types: list,
    tone: dict,
    allowed_shot_types: list = None,
) -> tuple:
    """카드 내용에 맞는 이미지 검색어와 구도를 Claude에게 만들게 한다. 과장된
    '전후비교' 느낌의 검색어는 피하고, 직전 카드들과 다른 구도를 고르도록 해서
    세트 전체가 '얼굴 클로즈업만 반복'되는 단조로움을 막는다. 인물이 나오는
    구도에는 동양인 모델이 더 잡히도록 검색어에 asian을 넣는다. 또한 decide_tone
    에서 미리 정해둔 톤 키워드를 검색어에 함께 넣어서, 애초에 통일된 톤의
    사진이 검색되게 한다.

    allowed_shot_types를 주면 그 목록으로만 shot_type을 고르게 강제한다 —
    "웬만하면 다른 구도를 고르라"는 프롬프트 지시만으로는 인물 사진(얼굴/
    상반신/일상 장면)이 여러 카드 연속으로 나오는 걸 막지 못했어서, 연속
    인물샷이 일정 횟수를 넘으면 호출하는 쪽(collect_photos)에서 인물 없는
    구도만 강제로 선택지에 남기는 방식으로 바꿨다. 프롬프트 지시보다 이렇게
    선택지 자체를 코드로 좁히는 쪽이 훨씬 확실하다."""
    allowed_shot_types = allowed_shot_types or SHOT_TYPES
    query_tool = {
        **QUERY_TOOL,
        "input_schema": {
            **QUERY_TOOL["input_schema"],
            "properties": {
                **QUERY_TOOL["input_schema"]["properties"],
                "shot_type": {
                    "type": "string",
                    "enum": allowed_shot_types,
                    "description": "이 카드에 쓸 사진의 구도. 직전 카드들과 겹치지 않게 다양하게 고른다.",
                },
            },
        },
    }

    recent_note = (
        f"바로 직전 카드들의 구도: {', '.join(recent_shot_types)}. 이번엔 이거랑 겹치지 않는 "
        "구도를 고르세요." if recent_shot_types else "이번이 첫 카드입니다."
    )
    forced_note = (
        f"\n\n(주의: 인물 사진이 너무 여러 카드 연속으로 나와서, 이번엔 인물이 안 나오는 구도"
        f"({', '.join(allowed_shot_types)}) 중에서만 골라야 합니다.)"
        if set(allowed_shot_types) != set(SHOT_TYPES)
        else ""
    )
    system_prompt = f"""당신은 스킨케어 카드뉴스에 쓸 이미지를 찾는 사진수집가입니다.
주어진 카드 문구에 어울리는 구도(shot_type)와 Unsplash 검색어(영어, 2~4단어)를 만드세요.

구도 선택 규칙:
- 얼굴 클로즈업(close_up_face)만 카드마다 반복되면 세트 전체가 단조롭고 붕어빵처럼
  보입니다. {recent_note}
- 정보 전달용 카드(핵심정보 등)는 얼굴보다 손동작/제품/질감 구도가 더 어울리는 경우가
  많습니다. 표지나 공감 유도 카드에만 인물 구도를 아껴서 쓰세요.{forced_note}

톤 통일 규칙 (중요):
- 이번 세트 전체는 "{tone['kr_label']}" 톤 하나로 통일합니다. 검색어에 "{tone['search_hint']}"를
  자연스럽게 포함시켜서(예: "hands applying cream {tone['search_hint']}") 같은 분위기의
  사진이 검색되게 하세요. 이건 나중에 밝기를 보정하는 게 아니라 처음부터 톤이 맞는 사진을
  찾기 위한 것이니 빠뜨리지 마세요.

검색어 규칙:
- 'before after' 같은 전후비교 느낌의 검색어는 피하세요.
- shot_type이 close_up_face 또는 half_body_portrait처럼 사람 얼굴/상반신이 나오는
  구도라면, 검색어에 "asian" 또는 "korean"을 넣어서(예: "asian woman skincare") 동양인
  모델 사진이 나올 확률을 높이세요. Unsplash에 한국인 사진만 골라 찾을 만큼 데이터가
  많지는 않지만, 기본 검색어보다는 서구권 모델 위주로 쏠리는 걸 줄여줍니다.
- 인물이 나오는 구도라면 "professional beauty editorial" 또는 "beauty campaign photography"
  같은 표현도 함께 넣어서, 캐주얼한 일상 스냅샷보다 조명·스타일링·구도가 잡힌 화보st
  사진이 검색되게 하세요(예: "asian woman skincare professional beauty editorial").
- 손/제품 구도(hands_action, product_flatlay)는 얼굴이 같이 나오지 않게, 검색어에
  "hands only" 또는 "no face" 같은 표현을 넣어서 손/제품만 명확히 나오는 사진을
  찾으세요 — 이 구도로 검색해도 얼굴이 같이 잡히는 사진이 많이 섞여 나와서 인물
  구도와 시각적으로 구분이 안 되는 문제가 있었습니다.
- 피부 트러블/여드름을 있는 그대로 클리닉/의학 사진처럼 적나라하게 보여주는 극단적
  클로즈업(모공, 뾰루지, 피부 질환이 그대로 보이는 매크로샷)은 보는 사람에게 부담스러운
  느낌을 주니 피하세요.
- 검색어는 항상 "무엇이 찍혀 있는지 한눈에 알 수 있는" 대상으로 만드세요. "종이 질감",
  "패브릭 주름", "추상적인 배경" 같은 스킨케어와 무관한 소재는 검색어에 절대 넣지
  마세요 — 카드 내용과 실제로 관련 있는 사물/사람/제품이 검색되게 하세요.

submit_query 도구로만 응답하세요."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=system_prompt,
        tools=[query_tool],
        tool_choice={"type": "tool", "name": "submit_query"},
        messages=[{"role": "user", "content": f"카드 역할: {role}\n카드 문구: {card_text}"}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_query":
            return block.input["query"], block.input["shot_type"]
    return "skincare", "product_flatlay"


PICK_TOOL = {
    "name": "submit_pick",
    "description": "후보 이미지 중 이 카드에 가장 어울리는 하나를 선택하거나, 다 별로면 없다고 표시한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "no_good_match": {
                "type": "boolean",
                "description": (
                    "후보 중 카드 내용과 명백히 관련 있는 사진이 하나도 없으면(예: 종이/패브릭/"
                    "추상적인 배경 질감처럼 스킨케어와 무관한 사진뿐이면) true. 이 경우 "
                    "chosen_index는 무시되니 아무 값이나 넣어도 된다."
                ),
            },
            "chosen_index": {"type": "integer", "description": "선택한 후보의 0부터 시작하는 인덱스"},
            "reason": {"type": "string", "description": "이 이미지를 고른 이유 (한 줄). no_good_match가 true면 왜 다 안 맞는지"},
        },
        "required": ["chosen_index", "reason"],
    },
}


def _fetch_image_block(url: str):
    """후보 이미지의 실제 썸네일을 다운로드해서 Claude 메시지에 넣을 수 있는
    base64 이미지 블록으로 바꾼다. alt_description 같은 텍스트 설명만으로는
    "종이 질감을 스킨케어라고 착각" 같은 일이 생기기 쉬워서, pick_best가
    사진을 실제로 보고 판단하게 하기 위한 함수다. 실패하면 None을 반환하고
    호출하는 쪽에서 텍스트 설명만으로 대체한다."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if not content_type.startswith("image/"):
            content_type = "image/jpeg"
        b64 = base64.b64encode(resp.content).decode("ascii")
        return {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": b64}}
    except Exception:
        return None


def pick_best(
    client: anthropic.Anthropic, card_text: str, role: str, candidates: list, tone: dict, shot_type: str = None, allow_reject: bool = True
) -> dict:
    """후보 이미지를 실제로(썸네일을 다운로드해서) 보고 카드에 가장 맞는 걸
    고른다. alt_description 텍스트만 보고 고르면 "종이 질감"을 "스킨케어와
    은유적으로 어울린다"고 억지로 갖다 붙이는 문제가 있었어서, 진짜 이미지를
    같이 넣어서 판단하게 한다. allow_reject=False면(검색어를 넓힌 재시도
    라운드) 카드가 통째로 빌 수 있는 상황이니 무조건 그나마 나은 걸 고르게
    한다.

    shot_type이 hands_action/product_flatlay처럼 인물이 없어야 하는 구도면,
    검색어에 이미 "no face" 류 키워드를 넣었어도 얼굴이 같이 나온 후보가
    섞여 들어올 수 있다(검색어만으로 완벽히 걸러지지 않음) — 후보를 실제로
    보고 있으니, 여기서 한 번 더 "얼굴이 나온 후보는 피하라"고 명시해서
    이중으로 막는다."""
    if not candidates:
        return None

    target_brightness = tone.get("target_brightness") if tone else None

    def tone_note(c):
        brightness = hex_to_brightness(c.get("color"))
        if brightness is None or target_brightness is None:
            return "톤 정보 없음"
        return "톤 잘 맞음" if abs(brightness - target_brightness) < 30 else "톤 차이 있음"

    content = [
        {
            "type": "text",
            "text": f"카드 역할: {role}\n카드 문구: {card_text}\n\n아래는 후보 이미지 {len(candidates)}장입니다. "
            "각 번호 바로 다음에 오는 이미지가 그 번호의 실제 사진입니다.",
        }
    ]
    for i, c in enumerate(candidates):
        ratio_note = "가까움" if abs(c["width"] / c["height"] - TARGET_RATIO) < 0.15 else "먼 편"
        content.append(
            {
                "type": "text",
                "text": f"[후보 {i}] 출처: {c['source_label']} / 설명텍스트: "
                f"{c.get('alt_description') or '(없음)'} / 4:5 근접도: {ratio_note} / {tone_note(c)}",
            }
        )
        img_block = _fetch_image_block(c.get("url_thumb") or c.get("url_regular"))
        content.append(img_block if img_block else {"type": "text", "text": "(이미지 로드 실패)"})

    cover_note = ""
    if role == "표지":
        cover_note = (
            "\n\n이 카드는 피드 첫 장(표지)입니다. 스크롤을 멈추게 할 만큼 시선을 끄는, 임팩트 있는 "
            "구도·표정·색감의 사진을 우선하세요. 밋밋하거나 애매해서 뭘 보여주는지 잘 안 와닿는 "
            "사진은 표지로 적합하지 않습니다."
        )

    polish_note = (
        "\n\n인물이 나오는 사진일 경우, 조명·구도·스타일링이 잘 잡힌 화보/캠페인st 사진을 우선하고, "
        "생활 스냅샷처럼 조명이 평범하거나 구도가 어색한 사진보다는 더 정돈되고 완성도 있어 보이는 "
        "쪽을 고르세요. 특정 인물의 외모를 평가하라는 게 아니라, 사진의 조명·스타일링·연출 완성도를 "
        "기준으로 판단하라는 뜻입니다."
    )

    no_face_note = ""
    if shot_type in NO_FACE_QUERY_SUFFIX:
        no_face_note = (
            "\n\n이 카드는 손/제품 구도(얼굴이 없어야 함)입니다. 검색어에 얼굴 배제 키워드를 넣었지만 "
            "그래도 얼굴이 같이 나온 후보가 섞여 있을 수 있습니다 — 얼굴이 뚜렷하게 보이는 후보는 "
            "피하고, 손/제품만 나온 후보를 우선하세요. 세트 안의 다른 카드들이 이미 얼굴 클로즈업"
            "위주라 이 카드까지 얼굴이 나오면 세트 전체가 비슷비슷하게 반복돼 보입니다."
        )

    if allow_reject:
        reject_note = (
            "\n\n중요: 후보 이미지를 실제로 봤을 때 카드 문구와 명백히 무관하거나(종이/패브릭/추상적인 "
            "배경 등), 뭘 보여주려는 건지 애매해서 카드 내용을 제대로 전달 못 한다면, 억지로 은유적인 "
            "연결고리를 만들어 고르지 마세요. 그런 후보뿐이면 no_good_match를 true로 표시하세요."
        )
    else:
        reject_note = (
            "\n\n이번엔 검색어를 넓힌 재시도 라운드입니다 — no_good_match를 쓰지 말고 후보 중 "
            "그나마 카드 내용에 가장 가까운 걸 반드시 하나 골라야 합니다."
        )

    tone_label = tone.get("kr_label", "") if tone else ""
    system_prompt = f"""당신은 스킨케어 카드뉴스 사진수집가입니다. 카드 문구와 실제 후보 이미지들을
직접 보고, 가장 자연스럽고 내용에 어울리는 사진을 고르세요. 과도하게 연출되거나 전후비교처럼
보이는 사진은 피하세요. 이번 세트는 "{tone_label}" 톤으로 통일하고 있습니다 — 내용 적합성이
비슷한 후보가 여럿이면 "톤 잘 맞음"으로 표시된 쪽을 우선하세요.{cover_note}{polish_note}{no_face_note}{reject_note}

submit_pick 도구로만 응답하세요."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=system_prompt,
        tools=[PICK_TOOL],
        tool_choice={"type": "tool", "name": "submit_pick"},
        messages=[{"role": "user", "content": content}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_pick":
            if allow_reject and block.input.get("no_good_match"):
                return None
            idx = block.input["chosen_index"]
            if not (0 <= idx < len(candidates)):
                if allow_reject:
                    return None
                idx = 0  # 강제 선택 라운드에서는 인덱스가 이상해도 첫 후보로라도 채운다
            if 0 <= idx < len(candidates):
                chosen = candidates[idx]
                ratio = chosen["width"] / chosen["height"]
                return {
                    "reason": block.input["reason"],
                    "source": chosen["source"],
                    "source_label": chosen["source_label"],
                    "photo_id": chosen["id"],
                    "url_regular": chosen["url_regular"],  # 너비 약 1080px 이상
                    "url_full": chosen["url_full"],
                    "download_location": chosen["download_location"],  # Pexels면 None
                    "photographer": chosen["photographer"],
                    "photographer_profile": chosen["photographer_profile"],
                    "alt_description": chosen.get("alt_description", ""),
                    "likes": chosen.get("likes"),  # Pexels는 None — 실제로 인기도 랭킹이 적용됐는지 눈으로 확인용
                    "original_width": chosen["width"],
                    "original_height": chosen["height"],
                    "aspect_ratio": round(ratio, 3),
                    # 정확히 0.8(4:5)이 아니어도 괜찮다 — 최종 크롭은 crop_images.py에서
                    # 4:5 규격에 맞춰 처리한다. 여기선 참고용 플래그만 남긴다.
                    "close_to_4_5": abs(ratio - TARGET_RATIO) < 0.1,
                }
    return None


def trigger_download_event(download_location: str, access_key: str):
    """Unsplash API 가이드라인: 실제로 쓰기로 한 이미지는 download_location에
    한 번 요청을 보내 다운로드로 집계되게 해야 한다 (사진작가에게 크레딧이
    돌아가는 절차). Pexels 사진은 이 절차가 없으니 호출하는 쪽에서 걸러야 한다.
    실패해도 전체 진행에는 지장 없게 조용히 넘어간다."""
    try:
        requests.get(
            download_location,
            headers={"Authorization": f"Client-ID {access_key}"},
            timeout=10,
        )
    except Exception as e:
        print(f"    (다운로드 집계 요청 실패, 무시하고 진행: {e})")


def collect_photos(script: dict) -> list:
    unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not unsplash_key:
        raise RuntimeError(
            "UNSPLASH_ACCESS_KEY 환경변수가 없습니다. "
            "unsplash.com/oauth/applications 에서 무료로 앱을 등록하고 Access Key를 발급받아 설정하세요."
        )
    pexels_key = os.environ.get("PEXELS_API_KEY")  # 없어도 동작은 함 (Unsplash만 씀)
    if not pexels_key:
        print(
            "(참고: PEXELS_API_KEY가 없어서 Unsplash만 검색해요. "
            "pexels.com/api 에서 무료 키를 받아 export PEXELS_API_KEY=... 하면 "
            "후보 풀이 넓어져서 원하는 톤/느낌의 사진을 찾기 더 쉬워져요.)\n"
        )

    client = anthropic.Anthropic()

    # 이번 세트에서 영구 차단된 사진작가/사진 ID를 한 번만 읽어둔다. 실행마다
    # 새로 읽어야 ban_photo.py로 방금 추가한 차단이 바로 다음 실행부터 반영된다.
    banned = load_banned()
    if banned["photographers"] or banned["photo_ids"]:
        print(
            f"(영구 차단 목록 적용: 작가 {len(banned['photographers'])}명, "
            f"사진 ID {len(banned['photo_ids'])}개 — ban_photo.py list로 확인 가능)\n"
        )

    # 카드 하나하나를 보기 전에 세트 전체 톤을 먼저 정한다 — 그래야 모든 카드의
    # 검색어/선택이 같은 기준을 따라서, 다 고른 다음 밝기를 맞추는 게 아니라
    # 처음부터 통일된 톤의 사진만 모이게 된다.
    tone = decide_tone(client, script)
    print(
        f"이번 세트 톤: {tone['kr_label']} (preset={tone['preset']}) — {tone['reason']}\n"
        f"  목표 밝기: {tone['target_brightness']} / 검색어 힌트: \"{tone['search_hint']}\"\n"
    )

    # 표지(hook) + 각 슬라이드 + 마무리(CTA)를 "이미지가 필요한 카드" 목록으로
    # 정리. 마무리 카드도 자기 사진을 따로 찾는다 — 예전엔 디자이너 단계에서
    # 마지막 슬라이드 사진을 그대로 재사용했는데, 그러면 캐러셀 마지막 두
    # 장(마지막 슬라이드 + 마무리)이 똑같은 사진으로 겹쳐 보이는 문제가 있었다.
    cards = [{"index": 1, "role": "표지", "text": script["hook"]}]
    cards += [{"index": s["index"], "role": s["role"], "text": s["text"]} for s in script["slides"]]
    closing_text = f"{script.get('cta', '')} {script.get('comment_question', '')}".strip()
    cards.append({"index": cards[-1]["index"] + 1, "role": "마무리", "text": closing_text})

    assignments = []
    used_ids = set()  # 중복 배정 방지용 — 이미 고른 사진의 unsplash id를 기록
    recent_shot_types = []  # 구도 다양성 확보용 — 직전 1~2장의 구도를 기록
    # 인물이 나오는 구도(close_up_face, half_body_portrait)가 연속으로 몇 번
    # 나왔는지 세는 카운터. MAX_CONSECUTIVE_PERSON_SHOTS에 도달하면 다음 카드는
    # QUERY_TOOL의 shot_type 선택지 자체를 인물 없는 구도로만 강제로 좁힌다.
    consecutive_person = 0
    for card in cards:
        print(f"  카드 {card['index']}({card['role']}) 이미지 찾는 중...")
        if consecutive_person >= MAX_CONSECUTIVE_PERSON_SHOTS:
            allowed_shot_types = [t for t in SHOT_TYPES if t not in PERSON_SHOT_TYPES]
        else:
            allowed_shot_types = SHOT_TYPES
        # 직전 카드와 완전히 같은 구도가 또 나오는 것도 막는다 — person 구도
        # 끼리(예: close_up_face 두 번 연속)뿐 아니라 hands_action 두 번
        # 연속처럼 person 카운터엔 안 잡히는 반복도 시각적으로 붕어빵처럼
        # 보이는 원인이었다. 선택지가 하나만 남으면(강제 상황) 그대로 둔다.
        if recent_shot_types and len(allowed_shot_types) > 1:
            allowed_shot_types = [t for t in allowed_shot_types if t != recent_shot_types[-1]] or allowed_shot_types
        query, shot_type = generate_query(
            client, card["text"], card["role"], recent_shot_types[-2:], tone, allowed_shot_types
        )
        # hands_action/product_flatlay는 검색어 자체에 얼굴 배제 키워드를
        # 코드로 강제해서, Claude가 깜빡하고 안 넣어도 항상 적용되게 한다.
        no_face_suffix = NO_FACE_QUERY_SUFFIX.get(shot_type)
        if no_face_suffix and no_face_suffix not in query:
            query = f"{query} {no_face_suffix}"
        candidates = gather_candidates(
            query, unsplash_key, pexels_key, used_ids, target_brightness=tone["target_brightness"], banned=banned
        )
        picked = pick_best(client, card["text"], card["role"], candidates, tone, shot_type=shot_type) if candidates else None

        # 여기로 오는 경우는 둘 중 하나다: (1) "asian"/"korean"+톤 키워드까지 붙인
        # 검색어가 너무 구체적이라 결과가 아예 없거나, (2) 결과는 있는데 다
        # 스킨케어와 무관한 사진뿐이라 pick_best가 억지로 고르지 않고 거절한
        # 경우. 두 경우 다 수식어를 떼고 핵심 단어(맨 앞 2단어)만 남긴 더 넓은
        # 검색어로 한 번 더 시도하고, 이번엔 allow_reject=False로 무조건 하나
        # 고르게 해서 카드가 통째로 빈 채로 남는 걸 막는다.
        if picked is None:
            fallback_query = " ".join(query.split()[:2]) or "skincare"
            print(f"    (적합한 사진 없음 — 검색어 단순화해서 재시도: \"{fallback_query}\")")
            fallback_candidates = gather_candidates(
                fallback_query,
                unsplash_key,
                pexels_key,
                used_ids,
                target_brightness=tone["target_brightness"],
                banned=banned,
            )
            fallback_picked = (
                pick_best(client, card["text"], card["role"], fallback_candidates, tone, shot_type=shot_type, allow_reject=False)
                if fallback_candidates
                else None
            )
            if fallback_picked is not None:
                query, picked = fallback_query, fallback_picked

        if picked is None:
            print(f"    -> 적절한 이미지를 못 찾음 (검색어: {query}, 구도: {shot_type})")
            assignments.append(
                {**card, "query": query, "shot_type": shot_type, "tone_preset": tone["preset"], "image": None}
            )
            recent_shot_types.append(shot_type)
            consecutive_person = consecutive_person + 1 if shot_type in PERSON_SHOT_TYPES else 0
            continue

        recent_shot_types.append(shot_type)
        consecutive_person = consecutive_person + 1 if shot_type in PERSON_SHOT_TYPES else 0
        used_ids.add(picked["photo_id"])
        if picked["source"] == "unsplash" and picked["download_location"]:
            trigger_download_event(picked["download_location"], unsplash_key)
        ratio_note = "4:5에 가까움" if picked["close_to_4_5"] else "4:5와 차이 있음(크롭 단계에서 보정)"
        likes_note = f"좋아요 {picked['likes']}개" if picked.get("likes") is not None else "인기도 정보 없음(Pexels)"
        print(
            f"    -> 선택됨: [{picked['source_label']}] {picked['photographer']} 작가 사진 "
            f"(구도: {shot_type}, {picked['original_width']}x{picked['original_height']}, "
            f"{ratio_note}, {likes_note}) — {picked['reason']}"
        )
        assignments.append(
            {**card, "query": query, "shot_type": shot_type, "tone_preset": tone["preset"], "image": picked}
        )

    return assignments


if __name__ == "__main__":
    script_path = Path(__file__).parent / "approved_script.json"
    if not script_path.exists():
        raise SystemExit(
            f"{script_path} 이 없습니다. 먼저 orchestrator.py를 실행해서 승인된 대본을 만들어두세요."
        )
    script = json.loads(script_path.read_text(encoding="utf-8"))

    print(f"'{script.get('topic', '')}' 카드뉴스에 쓸 이미지를 수집합니다...\n")
    assignments = collect_photos(script)

    out_path = Path(__file__).parent / "photo_assignments.json"
    out_path.write_text(json.dumps(assignments, ensure_ascii=False, indent=2), encoding="utf-8")

    found = sum(1 for a in assignments if a["image"] is not None)
    print(f"\n총 {len(assignments)}개 카드 중 {found}개에 이미지 배정 완료")
    print(f"저장 완료: {out_path}")
    print("(각 이미지는 출처(Unsplash/Pexels)와 저작자 표시(photographer/photographer_profile)를 함께 표시해야 해요)")
