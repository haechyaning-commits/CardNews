"""
photo_assignments.json에 배정된 이미지를 실제로 다운로드해서 인스타그램
캐러셀 정확한 규격(1080x1350px, 4:5)으로 크롭하고, 두 단계의 톤 보정을
거쳐 로컬 이미지 파일로 저장한다.

Unsplash는 사진마다 촬영 환경/보정이 전혀 다르기 때문에, "톤을 통일해줘"
같은 걸 검색어(AI 판단)만으로 완전히 보장할 수 없다. 그래서 크기를 코드로
강제한 것과 같은 방식으로, 톤도 크롭 이후 코드로 두 번 다듬는다.

1단계 - 밝기 통일: 카드 전체의 평균 밝기를 기준점으로 삼아 너무 어둡거나
너무 밝은 사진을 그 기준 쪽으로 당기고, 대비가 과한 사진은 살짝 눌러서
튀지 않게 한다.

2단계 - 계정 고유 필터: 참고 레퍼런스(따뜻하고 살짝 뮤트된 라이프스타일
톤)처럼, 채도를 살짝 낮추고 붉은기를 살짝 올리고 파란기를 살짝 내려서
"웜+뮤트" 색감을 모든 사진에 동일하게 입힌다. 이건 사진 원본이 뭐든 상관없이
항상 적용되는 계정 고유 필터라서, 사진 출처(작가/촬영환경)가 제각각이어도
피드 전체가 하나의 톤으로 보이게 만드는 핵심 장치다.

크롭 방식: 원본 비율이 4:5보다 넓으면 좌우를 가운데 기준으로 자르고,
4:5보다 좁고 길면 위아래를 가운데 기준으로 잘라서 정확히 4:5 비율을
만든 다음 1080x1350으로 리사이즈한다.

사용법
------
1. pip install Pillow requests
2. photo_assignments.json이 폴더에 있어야 한다 (먼저 photo_agent.py 실행).
3. python crop_images.py

결과: images/ 폴더에 card_01_표지.jpg 같은 이름으로 8장이 저장되고,
각 파일 경로와 밝기 보정값이 담긴 crop_manifest.json도 같이 생성된다.
"""

import io
import json
from pathlib import Path

import requests
from PIL import Image, ImageEnhance, ImageStat

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1350
TARGET_RATIO = TARGET_WIDTH / TARGET_HEIGHT  # 0.8

# 1단계: 톤(밝기) 보정 설정
MAX_BRIGHTNESS_SCALE = 1.5   # 너무 어두운 사진을 과하게 밝히면 화질이 깨져 보이므로 상한
MIN_BRIGHTNESS_SCALE = 0.7   # 너무 밝은 사진을 과하게 어둡게 만들면 부자연스러우므로 하한
CONTRAST_FACTOR = 0.9        # 1.0보다 살짝 낮춰서 카드 3처럼 대비가 튀는 사진을 완화

# 2단계: 계정 고유 "웜+뮤트" 필터 설정 (레퍼런스 참고)
BRAND_SATURATION = 0.9       # 1.0보다 낮춰서 채도를 살짝 죽인 뮤트한 느낌
BRAND_CONTRAST = 0.95        # 대비를 살짝 낮춰서 부드러운 필름 느낌
BRAND_WARM_R = 1.02          # 레드 채널을 아주 살짝만 올리고
BRAND_WARM_B = 0.98          # 블루 채널을 아주 살짝만 내려서 은은한 웜톤만 준다
# (원래 1.05/0.95였는데 "톤이 너무 누렇다"는 피드백을 받고 절반 이하로 줄임 —
# 이미 따뜻한 색의 사진(우드톤 배경 등)에 겹치면 과하게 노랗게 보이기 쉬움)


def crop_to_4x5(img: Image.Image) -> Image.Image:
    """이미지를 가운데 기준으로 정확히 4:5 비율로 잘라낸 뒤
    1080x1350으로 리사이즈해서 반환한다."""
    w, h = img.size
    current_ratio = w / h

    if current_ratio > TARGET_RATIO:
        # 가로가 상대적으로 넓다 -> 좌우를 잘라낸다
        new_w = int(h * TARGET_RATIO)
        left = (w - new_w) // 2
        box = (left, 0, left + new_w, h)
    else:
        # 세로가 상대적으로 길다 -> 위아래를 잘라낸다
        new_h = int(w / TARGET_RATIO)
        top = (h - new_h) // 2
        box = (0, top, w, top + new_h)

    cropped = img.crop(box)
    return cropped.resize((TARGET_WIDTH, TARGET_HEIGHT), Image.LANCZOS)


def safe_filename(text: str, max_len: int = 12) -> str:
    keep = "".join(c for c in text if c.isalnum())
    return keep[:max_len] if keep else "card"


def get_brightness(img: Image.Image) -> float:
    """이미지의 평균 밝기(그레이스케일 0~255 기준)를 계산한다."""
    return ImageStat.Stat(img.convert("L")).mean[0]


def normalize_tone(img: Image.Image, target_brightness: float) -> Image.Image:
    """이미지 밝기를 target_brightness 쪽으로 당기고, 대비를 살짝 낮춰서
    세트 전체의 톤을 통일시킨다. 보정 폭은 상/하한을 둬서 과보정으로 화질이
    깨지거나 부자연스러워지는 걸 막는다."""
    current = get_brightness(img)
    if current <= 0:
        scale = 1.0
    else:
        scale = target_brightness / current
    scale = max(MIN_BRIGHTNESS_SCALE, min(MAX_BRIGHTNESS_SCALE, scale))

    img = ImageEnhance.Brightness(img).enhance(scale)
    img = ImageEnhance.Contrast(img).enhance(CONTRAST_FACTOR)
    return img


def apply_brand_filter(img: Image.Image) -> Image.Image:
    """레퍼런스 계정처럼 따뜻하고 살짝 뮤트된 필름 톤을 모든 사진에 동일하게
    입힌다. normalize_tone이 '밝기를 세트 안에서 맞추는' 역할이라면, 이 함수는
    '어떤 사진이 들어와도 항상 같은 색감으로 만드는' 역할이라 순서상 항상
    마지막에 적용한다."""
    img = ImageEnhance.Color(img).enhance(BRAND_SATURATION)
    img = ImageEnhance.Contrast(img).enhance(BRAND_CONTRAST)

    r, g, b = img.split()
    r = r.point(lambda x: min(255, int(x * BRAND_WARM_R)))
    b = b.point(lambda x: int(x * BRAND_WARM_B))
    return Image.merge("RGB", (r, g, b))


def main():
    out_dir = Path(__file__).parent
    data_path = out_dir / "photo_assignments.json"
    if not data_path.exists():
        raise SystemExit(f"{data_path} 이 없습니다. 먼저 photo_agent.py를 실행하세요.")

    assignments = json.loads(data_path.read_text(encoding="utf-8"))

    images_dir = out_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # 1단계: 먼저 전부 다운로드 + 크롭만 해서 메모리에 들고, 각각의 밝기를 잰다.
    # 이 세트의 "목표 밝기"를 8장의 평균으로 잡아야 어느 한쪽(너무 밝거나
    # 너무 어두운 사진)에 나머지가 억지로 끌려가지 않는다.
    cropped_items = []
    for a in assignments:
        img_info = a.get("image")
        if img_info is None:
            print(f"카드 {a['index']}: 배정된 이미지 없음, 건너뜀")
            cropped_items.append((a, None))
            continue

        print(f"카드 {a['index']}({a['role']}) 다운로드 및 크롭 중...")
        resp = requests.get(img_info["url_regular"], timeout=30)
        resp.raise_for_status()

        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        cropped = crop_to_4x5(img)
        cropped_items.append((a, cropped))

    brightness_values = [get_brightness(c) for _, c in cropped_items if c is not None]
    if not brightness_values:
        raise SystemExit("크롭된 이미지가 하나도 없습니다.")
    target_brightness = sum(brightness_values) / len(brightness_values)
    before_spread = max(brightness_values) - min(brightness_values)
    print(
        f"\n이번 세트 목표 밝기: {target_brightness:.1f} "
        f"(보정 전 밝기 범위: {min(brightness_values):.1f} ~ {max(brightness_values):.1f}, "
        f"편차 {before_spread:.1f})\n"
    )

    # 2단계: 목표 밝기로 톤을 맞추면서 저장한다.
    manifest = []
    after_brightness_values = []
    for a, cropped in cropped_items:
        if cropped is None:
            manifest.append({**a, "local_path": None})
            continue

        before_b = get_brightness(cropped)
        toned = normalize_tone(cropped, target_brightness)
        toned = apply_brand_filter(toned)
        after_b = get_brightness(toned)
        after_brightness_values.append(after_b)

        filename = f"card_{a['index']:02d}_{safe_filename(a['role'])}.jpg"
        save_path = images_dir / filename
        toned.save(save_path, "JPEG", quality=90)

        print(
            f"  -> 저장: {save_path.name} ({toned.size[0]}x{toned.size[1]}, "
            f"밝기 {before_b:.1f} -> {after_b:.1f})"
        )
        manifest.append({
            **a,
            "local_path": str(save_path.relative_to(out_dir)),
            "brightness_before": round(before_b, 1),
            "brightness_after": round(after_b, 1),
        })

    manifest_path = out_dir / "crop_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    done = sum(1 for m in manifest if m["local_path"])
    after_spread = (
        max(after_brightness_values) - min(after_brightness_values)
        if after_brightness_values else 0
    )
    print(f"\n총 {len(manifest)}개 카드 중 {done}개 이미지 크롭 완료 (전부 정확히 {TARGET_WIDTH}x{TARGET_HEIGHT})")
    print(f"톤 보정 후 밝기 편차: {before_spread:.1f} -> {after_spread:.1f} (작을수록 톤이 통일된 것)")
    print(f"이미지 폴더: {images_dir}")
    print(f"매니페스트 저장: {manifest_path}")


if __name__ == "__main__":
    main()
