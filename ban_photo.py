"""
사진작가 또는 특정 사진을 앞으로 어떤 세트를 만들어도 다시는 후보에 안 뜨게
영구 차단하는 도구.

photo_agent.py는 실행할 때마다 매번 새로 Unsplash/Pexels를 검색하기 때문에,
"이번 세트에서만 빼줘"가 아니라 "이 작가/이 사진은 앞으로도 계속 빼줘"를
원한다면 그 정보를 파일로 남겨서 다음 실행에서도 읽어야 한다. 그 파일이
banned_photos.json이고, 이 스크립트가 그 파일을 관리하는 용도다.

photo_agent.py 쪽은 이 파일을 읽기만 한다(load_banned 함수). 실제로 항목을
추가/삭제/조회하는 건 전부 이 스크립트를 통해서 한다.

사용법
------
사진작가 이름으로 차단:
    python3 ban_photo.py photographer "Polina Tankilevitch"

특정 사진 ID로 차단 (미리보기 화면이나 photo_assignments.json에서 확인 가능,
예: "pexels_1234567", "unsplash_abcd1234"):
    python3 ban_photo.py id pexels_1234567

현재 차단 목록 확인:
    python3 ban_photo.py list

차단 해제(실수로 넣었거나 마음이 바뀐 경우):
    python3 ban_photo.py unban photographer "Polina Tankilevitch"
    python3 ban_photo.py unban id pexels_1234567
"""

import json
import sys
from pathlib import Path

BANNED_PATH = Path(__file__).parent / "banned_photos.json"


def load() -> dict:
    if BANNED_PATH.exists():
        try:
            data = json.loads(BANNED_PATH.read_text(encoding="utf-8"))
            return {
                "photographers": data.get("photographers", []),
                "photo_ids": data.get("photo_ids", []),
            }
        except Exception as e:
            print(f"(기존 파일을 읽는 데 실패해서 새로 시작해요: {e})")
    return {"photographers": [], "photo_ids": []}


def save(data: dict):
    BANNED_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def print_list(data: dict):
    print(f"\n차단된 사진작가 ({len(data['photographers'])}명):")
    if data["photographers"]:
        for name in data["photographers"]:
            print(f"  - {name}")
    else:
        print("  (없음)")

    print(f"\n차단된 사진 ID ({len(data['photo_ids'])}개):")
    if data["photo_ids"]:
        for pid in data["photo_ids"]:
            print(f"  - {pid}")
    else:
        print("  (없음)")
    print()


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)

    command = args[0]
    data = load()

    if command == "list":
        print_list(data)
        return

    if command == "photographer" and len(args) >= 2:
        name = args[1].strip()
        if name.lower() in {p.lower() for p in data["photographers"]}:
            print(f"이미 차단 목록에 있어요: {name}")
        else:
            data["photographers"].append(name)
            save(data)
            print(f"사진작가 차단 추가: {name}")
            print("(다음 photo_agent.py 실행부터 이 작가 사진은 후보에서 아예 제외돼요)")
        return

    if command == "id" and len(args) >= 2:
        photo_id = args[1].strip()
        if photo_id in data["photo_ids"]:
            print(f"이미 차단 목록에 있어요: {photo_id}")
        else:
            data["photo_ids"].append(photo_id)
            save(data)
            print(f"사진 ID 차단 추가: {photo_id}")
            print("(다음 photo_agent.py 실행부터 이 사진은 후보에서 아예 제외돼요)")
        return

    if command == "unban" and len(args) >= 3:
        target_type, value = args[1], args[2].strip()
        if target_type == "photographer":
            before = len(data["photographers"])
            data["photographers"] = [p for p in data["photographers"] if p.lower() != value.lower()]
            if len(data["photographers"]) < before:
                save(data)
                print(f"차단 해제: {value}")
            else:
                print(f"차단 목록에 없어요: {value}")
        elif target_type == "id":
            before = len(data["photo_ids"])
            data["photo_ids"] = [p for p in data["photo_ids"] if p != value]
            if len(data["photo_ids"]) < before:
                save(data)
                print(f"차단 해제: {value}")
            else:
                print(f"차단 목록에 없어요: {value}")
        else:
            print(__doc__)
            raise SystemExit(1)
        return

    print(__doc__)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
