"""
안정성 테스트 — 여러 주제로 작가+PM 오케스트레이터를 연속 실행해서
루프가 얼마나 안정적으로 통과하는지 확인한다.

각 주제마다 몇 번 만에 통과했는지, 반려됐다면 어떤 항목이 문제였는지를
모아서 stability_report.json과 터미널 요약으로 보여준다. 특정 체크
항목이 자꾸 반복해서 걸린다면 그 부분이 Skill 규칙을 더 손봐야 할
지점이라는 뜻이다.

사용법: python stability_test.py
(주제 5개 x 최대 3번 시도라 API 호출이 꽤 여러 번 나간다. 비용은
전체 다 돌려도 보통 1달러가 안 된다.)
"""

import json
from pathlib import Path

from orchestrator import run as run_pipeline

TEST_TOPICS = [
    "다크서클 완화 관리법",
    "여드름 흉터 관리",
    "지성 피부 유수분 밸런스",
    "민감성 피부 진정 루틴",
    "겨울철 피부 건조 관리",
]


def summarize_history(history):
    """각 시도에서 반려된 항목 이름만 뽑아서 요약한다."""
    rejected_reasons = []
    for attempt in history:
        review = attempt["review"]
        if review["approved"]:
            continue
        failed = [name for name, r in review["mechanical_results"].items() if not r["pass"]]
        judgment = review["judgment"]
        if not judgment["medical_claims_ok"]:
            failed.append("의학적 근거")
        if not judgment["engagement_ok"]:
            failed.append("완독 유도")
        if not judgment["no_gibberish"]:
            failed.append("텍스트 결함")
        rejected_reasons.append({"attempt": attempt["attempt"], "failed_items": failed})
    return rejected_reasons


def main():
    results = []
    out_dir = Path(__file__).parent

    for topic in TEST_TOPICS:
        print(f"\n{'=' * 50}\n주제: {topic}\n{'=' * 50}")
        run_pipeline(topic)

        # orchestrator.run()이 매번 review_log.json을 새로 저장하므로
        # 다음 주제로 넘어가기 전에 바로 읽어서 결과를 챙겨둔다.
        log = json.loads((out_dir / "review_log.json").read_text(encoding="utf-8"))

        results.append({
            "topic": topic,
            "final_status": log["final_status"],
            "attempts": log["attempts"],
            "rejected_reasons": summarize_history(log["history"]),
        })

    report_path = out_dir / "stability_report.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n\n===== 안정성 테스트 요약 =====")
    approved_count = 0
    all_failed_items = []
    for r in results:
        status = "✅" if r["final_status"] == "approved" else "⚠️"
        if r["final_status"] == "approved":
            approved_count += 1
        print(f"{status} {r['topic']}: {r['attempts']}번 시도, 최종 상태 {r['final_status']}")
        for rr in r["rejected_reasons"]:
            print(f"    - {rr['attempt']}차 반려 사유: {', '.join(rr['failed_items'])}")
            all_failed_items.extend(rr["failed_items"])

    print(f"\n전체 {len(results)}개 주제 중 {approved_count}개 최종 승인")
    if all_failed_items:
        from collections import Counter
        counts = Counter(all_failed_items)
        print("가장 자주 걸린 반려 항목:")
        for item, count in counts.most_common():
            print(f"  - {item}: {count}회")
    print(f"\n전체 리포트 저장: {report_path}")


if __name__ == "__main__":
    main()
