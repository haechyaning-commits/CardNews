"""
PM 에이전트 — 작가 에이전트가 만든 카드뉴스 대본을 검수해서
승인(approve) 또는 반려(reject)를 결정한다.

검수는 두 단계로 나뉜다.
1) 기계적 체크: 코드로 바로 판단 가능한 항목(카드 수, 면책 문구 포함 여부,
   금지된 단정적 표현, 슬라이드별 이모티콘/강조부호 포함 여부)을 API 호출
   없이 즉시 확인한다. 빠르고 결과가 항상 같다.
2) 판단 체크: 의학적 근거가 타당한지, 완독을 유도하는 장치가 충분한지,
   오타나 문맥에 안 맞는 단어가 섞여 있는지는 사람의 판단이 필요한
   영역이라 Claude에게 검수를 맡긴다.

이 파일의 체크 항목은 skill_beauty_skincare.md의 "5. PM 반려/통과
체크리스트" 섹션과 맞춰져 있다. Skill 문서를 수정하면 이 파일의 체크
항목도 같이 업데이트해야 한다. (이미지·템플릿 관련 항목은 디자이너/
사진수집가 에이전트가 아직 없어서 이 단계에서는 검사하지 않는다.)

단독 실행하면 output_script.json(작가 에이전트가 만든 최신 결과물)을
검수해서 결과를 보여준다.
"""

import json
from pathlib import Path
from typing import Tuple

import anthropic

from shared_rules import BANNED_ABSOLUTE_PHRASES, EMOTION_MARKERS

MODEL = "claude-sonnet-5"


# ---------- 0) 구조 검증 ----------
# tool-use로 스키마를 강제해도 가끔 중첩 배열의 항목 타입이 깨질 수 있다
# (예: slides의 한 항목이 객체가 아니라 문자열로 오는 경우). 이걸 검증 없이
# 바로 다음 체크로 넘기면 .get() 호출에서 그대로 에러가 나면서 전체 스크립트가
# 멈춘다. 그래서 다른 체크를 돌리기 전에 구조부터 확인하고, 깨져 있으면
# 그 자체를 반려 사유로 삼아 작가 에이전트에게 다시 쓰게 한다.

def validate_structure(draft: dict) -> Tuple[bool, str]:
    if not isinstance(draft, dict):
        return False, f"대본 전체가 객체(dict)가 아니라 {type(draft).__name__} 타입입니다."

    slides = draft.get("slides")
    if not isinstance(slides, list):
        return False, "'slides' 필드가 배열이 아닙니다."

    for i, s in enumerate(slides):
        if not isinstance(s, dict):
            return False, (
                f"slides[{i}] 항목이 객체가 아니라 {type(s).__name__} 타입입니다. "
                "각 슬라이드는 반드시 {'index': .., 'role': .., 'text': ..} 형태의 객체여야 합니다."
            )
        for key in ("index", "role", "text"):
            if key not in s:
                return False, f"slides[{i}] 항목에 '{key}' 키가 없습니다."

    for key in ("hook", "cta", "comment_question", "caption", "hashtags", "disclaimer_included"):
        if key not in draft:
            return False, f"'{key}' 필드가 대본에 없습니다."

    return True, "구조 검증 통과"


# ---------- 1) 기계적 체크 (API 호출 없음) ----------

def check_slide_count(draft: dict) -> Tuple[bool, str]:
    total = 1 + len(draft.get("slides", []))  # hook(1장) + slides
    ok = 7 <= total <= 10
    return ok, f"총 슬라이드 {total}장 (기준: 7~10장)"


def check_disclaimer(draft: dict) -> Tuple[bool, str]:
    ok = bool(draft.get("disclaimer_included"))
    return ok, "면책 문구 포함 여부: " + ("포함됨" if ok else "누락됨")


def check_absolute_phrases(draft: dict) -> Tuple[bool, str]:
    all_text = (
        draft.get("hook", "")
        + " " + " ".join(s.get("text", "") for s in draft.get("slides", []))
        + " " + draft.get("caption", "")
    )
    found = [p for p in BANNED_ABSOLUTE_PHRASES if p in all_text]
    ok = len(found) == 0
    return ok, ("단정적 표현 없음" if ok else f"단정적 표현 발견: {found}")


def check_emotion_markers(draft: dict) -> Tuple[bool, str]:
    missing = []
    for s in draft.get("slides", []):
        text = s.get("text", "")
        if not any(marker in text for marker in EMOTION_MARKERS):
            missing.append(s.get("index"))
    ok = len(missing) == 0
    return ok, ("모든 슬라이드에 이모티콘/강조부호 포함됨" if ok
                else f"이모티콘/강조부호 없는 슬라이드 번호: {missing}")


MECHANICAL_CHECKS = [
    ("슬라이드 7~10장", check_slide_count),
    ("면책 문구 포함", check_disclaimer),
    ("단정적 표현 없음", check_absolute_phrases),
    ("슬라이드별 이모티콘/강조부호", check_emotion_markers),
]


# ---------- 2) 판단 체크 (Claude 호출) ----------

JUDGMENT_TOOL = {
    "name": "submit_review",
    "description": "카드뉴스 대본에 대한 판단 기반 검수 결과를 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "medical_claims_ok": {
                "type": "boolean",
                "description": "의학적/피부관리 관련 주장이 근거 있고 조건부로 표현되어 있는가",
            },
            "medical_claims_issue": {"type": "string", "description": "문제가 있다면 구체적으로, 없으면 빈 문자열"},
            "engagement_ok": {
                "type": "boolean",
                "description": "완독을 유도하는 장치(전환 문구, 반전 요소)가 충분한가",
            },
            "engagement_issue": {"type": "string"},
            "no_gibberish": {
                "type": "boolean",
                "description": "오타, 문맥에 안 맞는 단어(예: 엉뚱한 영어 단어가 끼는 등)가 없는가",
            },
            "gibberish_issue": {"type": "string"},
            "overall_feedback": {
                "type": "string",
                "description": "반려 시 작가 에이전트가 바로 이해할 수 있는 구체적 수정 지시. 통과 시엔 간단한 총평",
            },
        },
        "required": [
            "medical_claims_ok", "medical_claims_issue",
            "engagement_ok", "engagement_issue",
            "no_gibberish", "gibberish_issue",
            "overall_feedback",
        ],
    },
}

JUDGMENT_SYSTEM_PROMPT = """당신은 스킨케어 인스타그램 카드뉴스를 검수하는 깐깐한 PM입니다.
아래 세 가지를 판단하세요.
1. 의학/피부관리 주장이 근거 있고, "무조건" 같은 단정적 표현이 아니라 "도움될 수 있어요" 같은 조건부 표현으로 되어 있는가
2. 카드뉴스가 끝까지 읽고 싶어지는 구성인가 — 문제제기, 정보, 반전 요소가 자연스럽게 이어지는가
3. 오타나 문맥에 맞지 않는 엉뚱한 단어(다른 언어 단어가 이유 없이 섞이는 등)가 없는가

트집을 잡기 위한 검수가 아니라, 실제로 게시했을 때 문제가 될 만한 것만 반려 사유로 삼으세요.
submit_review 도구로만 결과를 제출하세요."""


def judgment_review(draft: dict) -> dict:
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=JUDGMENT_SYSTEM_PROMPT,
        tools=[JUDGMENT_TOOL],
        tool_choice={"type": "tool", "name": "submit_review"},
        messages=[
            {
                "role": "user",
                "content": f"검수할 대본:\n{json.dumps(draft, ensure_ascii=False, indent=2)}",
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_review":
            return block.input

    raise RuntimeError("PM 에이전트가 구조화된 검수 결과를 반환하지 않았습니다.")


# ---------- 종합 ----------

def review_script(draft: dict) -> dict:
    """draft를 검수해서 승인/반려 여부와 구체적 피드백을 반환한다."""
    struct_ok, struct_detail = validate_structure(draft)
    if not struct_ok:
        # 구조 자체가 깨졌으면 나머지 체크는 의미가 없다(에러만 남).
        # 바로 반려 처리하고 작가 에이전트에게 형식을 맞춰 다시 쓰라고 알려준다.
        return {
            "approved": False,
            "mechanical_pass": False,
            "judgment_pass": False,
            "mechanical_results": {"구조 검증": {"pass": False, "detail": struct_detail}},
            "judgment": None,
            "feedback": (
                f"- [구조 검증] {struct_detail}\n"
                "- [종합 의견] 대본 형식이 스키마와 맞지 않아 다른 항목은 검수하지 못했습니다. "
                "반드시 지정된 JSON 스키마(slides는 각각 index/role/text를 가진 객체)에 맞춰 다시 작성하세요."
            ),
        }

    mechanical_results = {}
    mechanical_pass = True
    for name, check_fn in MECHANICAL_CHECKS:
        ok, detail = check_fn(draft)
        mechanical_results[name] = {"pass": ok, "detail": detail}
        if not ok:
            mechanical_pass = False

    judgment = judgment_review(draft)
    judgment_pass = (
        judgment["medical_claims_ok"]
        and judgment["engagement_ok"]
        and judgment["no_gibberish"]
    )

    approved = mechanical_pass and judgment_pass

    feedback_lines = []
    for name, result in mechanical_results.items():
        if not result["pass"]:
            feedback_lines.append(f"- [{name}] {result['detail']}")
    if not judgment["medical_claims_ok"]:
        feedback_lines.append(f"- [의학적 근거] {judgment['medical_claims_issue']}")
    if not judgment["engagement_ok"]:
        feedback_lines.append(f"- [완독 유도] {judgment['engagement_issue']}")
    if not judgment["no_gibberish"]:
        feedback_lines.append(f"- [텍스트 결함] {judgment['gibberish_issue']}")
    feedback_lines.append(f"- [종합 의견] {judgment['overall_feedback']}")

    return {
        "approved": approved,
        "mechanical_pass": mechanical_pass,
        "judgment_pass": judgment_pass,
        "mechanical_results": mechanical_results,
        "judgment": judgment,
        "feedback": "\n".join(feedback_lines),
    }


if __name__ == "__main__":
    script_path = Path(__file__).parent / "output_script.json"
    if not script_path.exists():
        raise SystemExit(
            f"{script_path} 이 없습니다. 먼저 writer_agent.py를 실행해서 대본을 만들어두세요."
        )
    draft = json.loads(script_path.read_text(encoding="utf-8"))
    result = review_script(draft)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n" + ("✅ 승인" if result["approved"] else "❌ 반려") )
