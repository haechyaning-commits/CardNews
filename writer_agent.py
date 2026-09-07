"""
작가(Writer) 에이전트 — 카드뉴스 대본 생성 스크립트

skill_beauty_skincare.md 의 "정확성 원칙"과 "작가 규칙" 섹션을 읽어와
시스템 프롬프트에 반영하고, 주제 하나를 받아 구조화된(JSON) 카드뉴스
대본을 생성한다.

사용법
------
1. 이 파일과 skill_beauty_skincare.md를 같은 폴더에 둔다.
2. 터미널에서 ANTHROPIC_API_KEY 환경변수를 설정한다.
   (macOS/Linux)  export ANTHROPIC_API_KEY="sk-ant-..."
3. 패키지를 설치한다.        pip install anthropic
4. 실행한다.                 python writer_agent.py "환절기 피부 트러블 관리"
   주제를 안 넣으면 기본 주제로 테스트가 실행된다.
"""

import json
import sys
from pathlib import Path
from typing import Optional

import anthropic

from shared_rules import BANNED_ABSOLUTE_PHRASES, EMOTION_MARKERS

SKILL_PATH = Path(__file__).parent / "skill_beauty_skincare.md"
MODEL = "claude-sonnet-5"
DEFAULT_TOPIC = "환절기 피부 트러블 관리"


def load_writer_skill(skill_path: Path) -> str:
    """Skill 문서에서 작가 에이전트에게 필요한 부분(1번 정확성 원칙 + 2번
    작가 규칙)만 잘라서 반환한다. 3번(디자이너 규칙)부터는 작가에게 불필요한
    정보라 프롬프트를 가볍게 유지하기 위해 제외한다."""
    if not skill_path.exists():
        raise FileNotFoundError(
            f"Skill 문서를 찾을 수 없습니다: {skill_path}\n"
            "skill_beauty_skincare.md를 이 스크립트와 같은 폴더에 두세요."
        )
    text = skill_path.read_text(encoding="utf-8")
    start = text.find("## 1.")
    end = text.find("## 3.")
    if start == -1 or end == -1:
        # 섹션 구분을 못 찾으면 안전하게 문서 전체를 반환한다.
        return text
    return text[start:end].strip()


# 작가 에이전트가 결과를 제출할 때 반드시 이 형식(JSON 스키마)에 맞추도록
# Claude의 tool-use 기능으로 출력 형식을 강제한다. 자유 텍스트로 받으면
# 다음 단계(디자이너·PM)에서 다시 파싱해야 하는 문제가 생긴다.
WRITER_OUTPUT_TOOL = {
    "name": "submit_card_news_script",
    "description": "완성된 카드뉴스 대본을 구조화된 형식으로 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "이번 카드뉴스의 주제"},
            "hook": {
                "type": "string",
                "description": "1장(표지) 문구. 3줄 이내, 질문형/숫자형/공감형 중 하나",
            },
            "slides": {
                "type": "array",
                "description": "2장부터 정보 카드까지의 슬라이드 목록 (보통 5~7개)",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "몇 번째 카드인지"},
                        "role": {
                            "type": "string",
                            "enum": ["배경설명", "핵심정보", "반전인사이트"],
                        },
                        "text": {"type": "string"},
                    },
                    "required": ["index", "role", "text"],
                },
            },
            "cta": {
                "type": "string",
                "description": "마지막 장 저장 유도 문구 (예: '저장해두고 나중에 써먹어요')",
            },
            "comment_question": {
                "type": "string",
                "description": "댓글 참여를 유도하는 질문 (답하기 쉬운 형태)",
            },
            "caption": {
                "type": "string",
                "description": "게시글 캡션 전체 텍스트. 질문으로 시작해서 질문으로 끝난다",
            },
            "hashtags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "니치/중간/대형/계정 시그니처 해시태그를 섞은 목록",
            },
            "disclaimer_included": {
                "type": "boolean",
                "description": "면책 문구('개인차가 있을 수 있어요' 등)를 caption 또는 마지막 슬라이드에 포함했는지",
            },
        },
        "required": [
            "topic",
            "hook",
            "slides",
            "cta",
            "comment_question",
            "caption",
            "hashtags",
            "disclaimer_included",
        ],
    },
}


def build_system_prompt(writer_skill: str) -> str:
    banned_list = ", ".join(f'"{p}"' for p in BANNED_ABSOLUTE_PHRASES)
    marker_list = ", ".join(EMOTION_MARKERS)
    return f"""당신은 20~30대 여성을 타겟으로 하는 스킨케어 인스타그램 카드뉴스 전문 작가입니다.
아래 지침을 반드시 지켜서 대본을 작성하세요. 지침에 없는 의학적 주장은 절대 만들어내지 마세요.

{writer_skill}

[제출 전 필수 자가 점검 — 이 목록은 PM 에이전트가 실제로 검사하는 항목과 동일합니다.
하나라도 어기면 반려되어 다시 써야 하니, 제출 전에 하나씩 직접 확인하세요]
1. 다음 표현은 절대 쓰지 않는다: {banned_list}
2. slides 배열의 모든 항목을 하나씩 확인한다 — 각 항목의 text 안에 다음 중 최소 하나가
   들어있어야 한다: {marker_list}. 빠진 슬라이드가 있으면 억지로라도 채워 넣고 제출한다.
3. caption에서 "~도 담아뒀어요", "~도 정리했어요"처럼 언급한 내용이 실제 slides 안에
   전부 들어있는지 확인한다. caption이 예고만 하고 실제 슬라이드에 없는 내용이 있으면 안 된다.

작성이 끝나면 반드시 submit_card_news_script 도구를 호출해서 결과를 제출하세요.
자유 텍스트로 답하지 말고 반드시 도구 호출로만 응답하세요."""


def generate_script(topic: str, feedback: Optional[str] = None) -> dict:
    """topic으로 대본을 생성한다. feedback이 주어지면(PM에게 반려당한 경우)
    이전 시도의 문제점을 알려주고 그걸 반영해서 다시 쓰도록 지시한다."""
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수를 자동으로 사용

    writer_skill = load_writer_skill(SKILL_PATH)
    system_prompt = build_system_prompt(writer_skill)

    user_message = f"이번 주제: {topic}"
    if feedback:
        user_message += (
            "\n\n[중요] 이전 시도가 PM 에이전트에게 반려되었습니다. "
            "아래 피드백을 반드시 반영해서 다시 작성하세요:\n" + feedback
        )

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system_prompt,
        tools=[WRITER_OUTPUT_TOOL],
        tool_choice={"type": "tool", "name": "submit_card_news_script"},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_card_news_script":
            return block.input

    raise RuntimeError("작가 에이전트가 구조화된 출력을 반환하지 않았습니다. 응답을 확인하세요:\n" + str(response))


def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TOPIC
    print(f"주제: {topic}\n생성 중...\n")

    result = generate_script(topic)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    out_path = Path(__file__).parent / "output_script.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장 완료: {out_path}")
    print("(이 JSON 파일을 다음 단계인 디자이너/PM 에이전트가 입력으로 사용하게 됩니다)")


if __name__ == "__main__":
    main()
