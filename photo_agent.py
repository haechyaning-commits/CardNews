"""
사진수집가(Photo Collector) 에이전트

approved_script.json(작가+PM 통과본)을 읽어서 카드(표지+슬라이드)마다
어울리는 이미지를 Unsplash에서 찾아 배정한다. Skill 문서 4번(사진수집가
규칙)에 따라 라이선스 프리 소스만 쓰고, 전후비교 느낌의 이미지는 피하도록
한다.

동작 순서
--------
1. 카드마다 Claude가 Unsplash 검색어(영어)를 만든다.
2. Unsplash Search API로 후보 이미지 5장을 가져온다.
3. Claude가 후보 설명을 보고 카드 내용에 가장 잘 맞는 걸 고른다.
4. 실제로 쓰기로 한 이미지는 Unsplash 가이드라인에 따라 download_location에
   요청을 보내 다운로드로 집계되게 한다 (사진작가에게 크레딧이 가는 절차).
5. 결과(이미지 URL, 저작자 이름/프로필, alt 텍스트)를 photo_assignments.json
   으로 저장한다. 이 파일이 다음 단계(디자이너 에이전트)의 입력이 된다.

주의: 이미지 파일 자체를 다운로드해서 저장하지 않고 Unsplash가 제공하는
URL을 그대로 쓴다 — Unsplash API 가이드라인상 이미지를 직접 다운로드해
자체 서버에 영구 보관하는 것은 권장되지 않는다.

사용법
------
1. unsplash.com/oauth/applications 에서 무료로 앱을 등록하고 Access Key를
   발급받아 환경변수로 설정한다.
       export UNSPLASH_ACCESS_KEY="여기에-발급받은-키"
   (초기엔 시간당 50 요청 제한인데, 카드 한 세트에 8번 정도만 쓰니 충분하다)
2. ANTHROPIC_API_KEY도 그대로 설정되어 있어야 한다.
3. approved_script.json이 폴더에 있어야 한다 (먼저 orchestrator.py 실행).
4. python photo_agent.py
"""

import json
import os
from pathlib import Path

import anthropic
import requests

MODEL = "claude-sonnet-5"
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"


def unsplash_search(query: str, access_key: str, per_page: int = 5) -> list:
    resp = requests.get(
        UNSPLASH_SEARCH_URL,
        params={"query": query, "per_page": per_page, "orientation": "portrait"},
        headers={"Authorization": f"Client-ID {access_key}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


QUERY_TOOL = {
    "name": "submit_query",
    "description": "이 카드에 어울리는 이미지를 찾기 위한 영어 검색어를 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Unsplash에서 검색할 영어 키워드 (2~4단어)"},
        },
        "required": ["query"],
    },
}


def generate_query(client: anthropic.Anthropic, card_text: str, role: str) -> str:
    """카드 내용에 맞는 이미지 검색어를 Claude에게 만들게 한다. 과장된
    '전후비교' 느낌의 검색어는 피하고 자연스러운 사진을 찾도록 지시한다."""
    system_prompt = """당신은 스킨케어 카드뉴스에 쓸 이미지를 찾는 사진수집가입니다.
주어진 카드 문구에 어울리는 Unsplash 검색어(영어, 2~4단어)를 만드세요.
'before after' 같은 전후비교 느낌의 검색어는 피하고, 자연스러운 스킨케어/피부/
일상 사진을 찾을 수 있는 검색어로 만드세요. submit_query 도구로만 응답하세요."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=system_prompt,
        tools=[QUERY_TOOL],
        tool_choice={"type": "tool", "name": "submit_query"},
        messages=[{"role": "user", "content": f"카드 역할: {role}\n카드 문구: {card_text}"}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_query":
            return block.input["query"]
    return "skincare"


PICK_TOOL = {
    "name": "submit_pick",
    "description": "후보 이미지 중 이 카드에 가장 어울리는 하나를 선택한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "chosen_index": {"type": "integer", "description": "선택한 후보의 0부터 시작하는 인덱스"},
            "reason": {"type": "string", "description": "이 이미지를 고른 이유 (한 줄)"},
        },
        "required": ["chosen_index", "reason"],
    },
}


def pick_best(client: anthropic.Anthropic, card_text: str, candidates: list):
    """후보 이미지들의 설명(alt_description)을 보고 카드에 가장 맞는 걸 고른다."""
    if not candidates:
        return None

    candidate_summaries = "\n".join(
        f"{i}. {c.get('alt_description') or c.get('description') or '(설명 없음)'}"
        for i, c in enumerate(candidates)
    )

    system_prompt = """당신은 스킨케어 카드뉴스 사진수집가입니다. 아래 카드 문구와
후보 이미지 설명 목록을 보고, 가장 자연스럽고 내용에 어울리는 사진을 고르세요.
과도하게 연출되거나 전후비교처럼 보이는 사진은 피하세요. submit_pick 도구로만 응답하세요."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=system_prompt,
        tools=[PICK_TOOL],
        tool_choice={"type": "tool", "name": "submit_pick"},
        messages=[
            {"role": "user", "content": f"카드 문구: {card_text}\n\n후보:\n{candidate_summaries}"}
        ],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_pick":
            idx = block.input["chosen_index"]
            if 0 <= idx < len(candidates):
                chosen = candidates[idx]
                return {
                    "reason": block.input["reason"],
                    "unsplash_id": chosen["id"],
                    "url_regular": chosen["urls"]["regular"],  # 너비 약 1080px
                    "url_full": chosen["urls"]["full"],
                    "download_location": chosen["links"]["download_location"],
                    "photographer": chosen["user"]["name"],
                    "photographer_profile": chosen["user"]["links"]["html"],
                    "alt_description": chosen.get("alt_description") or chosen.get("description") or "",
                }
    return None


def trigger_download_event(download_location: str, access_key: str):
    """Unsplash API 가이드라인: 실제로 쓰기로 한 이미지는 download_location에
    한 번 요청을 보내 다운로드로 집계되게 해야 한다 (사진작가에게 크레딧이
    돌아가는 절차). 실패해도 전체 진행에는 지장 없게 조용히 넘어간다."""
    try:
        requests.get(
            download_location,
            headers={"Authorization": f"Client-ID {access_key}"},
            timeout=10,
        )
    except Exception as e:
        print(f"    (다운로드 집계 요청 실패, 무시하고 진행: {e})")


def collect_photos(script: dict) -> list:
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not access_key:
        raise RuntimeError(
            "UNSPLASH_ACCESS_KEY 환경변수가 없습니다. "
            "unsplash.com/oauth/applications 에서 무료로 앱을 등록하고 Access Key를 발급받아 설정하세요."
        )

    client = anthropic.Anthropic()

    # 표지(hook) + 각 슬라이드를 "이미지가 필요한 카드" 목록으로 정리
    cards = [{"index": 1, "role": "표지", "text": script["hook"]}]
    cards += [{"index": s["index"], "role": s["role"], "text": s["text"]} for s in script["slides"]]

    assignments = []
    for card in cards:
        print(f"  카드 {card['index']}({card['role']}) 이미지 찾는 중...")
        query = generate_query(client, card["text"], card["role"])
        candidates = unsplash_search(query, access_key)
        picked = pick_best(client, card["text"], candidates)

        if picked is None:
            print(f"    -> 적절한 이미지를 못 찾음 (검색어: {query})")
            assignments.append({**card, "query": query, "image": None})
            continue

        trigger_download_event(picked["download_location"], access_key)
        print(f"    -> 선택됨: {picked['photographer']} 작가 사진 ({picked['reason']})")
        assignments.append({**card, "query": query, "image": picked})

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
    print("(각 이미지는 Unsplash 저작자 표시(photographer/photographer_profile)를 함께 표시해야 해요)")
