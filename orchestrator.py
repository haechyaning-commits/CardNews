"""
오케스트레이터 — 작가 에이전트와 PM 에이전트를 연결해서
반려/통과 루프를 실제로 실행한다.

동작 순서
--------
1. 작가 에이전트가 대본 초안을 작성한다.
2. PM 에이전트가 검수해서 승인/반려를 결정한다.
3. 반려면 PM의 피드백을 작가에게 전달해서 다시 쓰게 한다 (최대 MAX_REVISIONS회).
4. 승인되면 최종본을 저장한다. 최대 횟수까지 갔는데도 반려면 마지막
   시도본을 "미승인" 상태로 저장하고 경고를 띄운다.

전체 시도 기록(매 시도의 대본 + PM 피드백)을 review_log.json에 남겨서
"반려 몇 번 만에 통과했는지"를 나중에 포트폴리오에서 그대로 보여줄 수 있게 한다.

사용법: python orchestrator.py "환절기 피부 트러블 관리"
"""

import json
import sys
from pathlib import Path

from writer_agent import generate_script
from pm_agent import review_script

MAX_REVISIONS = 3


def run(topic: str) -> dict:
    history = []
    feedback = None
    draft = None
    review = None

    for attempt in range(1, MAX_REVISIONS + 1):
        print(f"\n=== 시도 {attempt}/{MAX_REVISIONS} ===")
        print("작가 에이전트 작성 중...")
        draft = generate_script(topic, feedback=feedback)

        print("PM 에이전트 검수 중...")
        review = review_script(draft)

        history.append({"attempt": attempt, "draft": draft, "review": review})

        if review["approved"]:
            print(f"\n✅ {attempt}번째 시도에서 통과했습니다!")
            save_results(topic, draft, history, final_status="approved")
            return draft

        print(f"❌ 반려됨. 사유:\n{review['feedback']}")
        feedback = review["feedback"]

    print(f"\n⚠️ {MAX_REVISIONS}회 시도 후에도 통과하지 못했습니다. 마지막 시도본을 저장합니다.")
    save_results(topic, draft, history, final_status="max_revisions_reached")
    return draft


def save_results(topic, draft, history, final_status):
    out_dir = Path(__file__).parent
    (out_dir / "approved_script.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "review_log.json").write_text(
        json.dumps(
            {"topic": topic, "final_status": final_status, "attempts": len(history), "history": history},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n최종본 저장: {out_dir / 'approved_script.json'}")
    print(f"전체 시도 기록 저장: {out_dir / 'review_log.json'}  (몇 번 만에 통과했는지 여기서 확인 가능)")


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "환절기 피부 트러블 관리"
    run(topic)
