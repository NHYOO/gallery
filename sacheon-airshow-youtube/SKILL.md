---
name: sacheon-airshow-youtube
description: 사천에어쇼 취재 사진이나 사진 기사로 정확히 60초(1920×1080, 16:9, 30fps) 유튜브용 Vox-inspired 항공 모션그래픽 MP4를 만드는 Codex 스킬. 블랙이글스, KF-21, 항공기 소개, 설계도/HUD/사진 전환, 하이라이트, 엔딩을 Python+FFmpeg로 자동 렌더. 사용자가 "사천에어쇼 영상", "하늘을 설계하다", "사진으로 유튜브 영상", "항공 쇼 모션그래픽" 등을 요청하면 활용. 웹용 세로 쇼츠가 아닌 가로형 본편용.
---

# 2026 사천에어쇼 — 하늘을 설계하다 (60초, 16:9)

**목표**: 기사와 직접 촬영한 사진을 사용해, 실제 재생 가능한 **60.000초 / 1920×1080 / 30fps / H.264 MP4**를 렌더하고 파일 위치와 결과 검증을 보고한다. 설명이나 코드만 작성하고 멈추지 않는다. **사용자의 작업량 최소화**가 우선이다.

이 스킬은 구형 `gallery-vox-style` (Remotion 9:16) 스킬을 원본으로 참고했지만, 시스템 리소스와 토큰을 아끼기 위해 **독립적인 Pillow+FFmpeg 가로형 렌더러**를 사용한다. 무거운 PyTorch, 사진인식 모델, Remotion 및 edge-tts는 설치하거나 요구하지 않는다. **내레이션 없이 자막 중심**, 선택적으로 직접 합성한 전자음만 쓴다. 영상은 영상생성 모델이 만든 가상 비행 장면이 아니라 **실제 촬영 사진을 코드 기반 그래픽으로 움직인 결과물**이다.

## 필수 규칙

- 기사: `https://www.ajunews.com/view/20261023150655387` (2026-10-23, '[광화문 갤러리] 파란 하늘을 도화지 삼아, 사천을 수놓은 비행'). 원문 기사를 읽을 수 있는 환경에서는 날짜·기종·행사 사실을 확인한다.
- 사용자가 제공한 사진만 사용한다. 존재하지 않는 항공기나 편대를 합성·생성하지 않는다. 영상에서 사진을 실제 움직이는 촬영 원본으로 오인하게 만들지 않는다.
- **항공기 개별 기종명은 사진으로 확인된 경우에만 표시한다.** KF-21 사진이 분명히 확인되면 `input/manifest.json`의 `categories.kf21`에 이름을 지정한다. 없다면 렌더러가 'AIRCRAFT' 일반 표기로 안전하게 대체한다. `assets/demo_photos/f35.jpg` 같은 파일명을 사실 검증 근거로 쓰지 않는다.
- 가로형 16:9. 예전 스킬의 `1080×1920`이나 세로 쇼츠 전용 레이아웃 코드를 그대로 가져오지 않는다.
- 이미지 수십 장을 채팅 메시지에 첨부하지 않는다. **프로젝트 폴더에 파일로 둔 뒤 경로만 사용**한다. ZIP은 단 한 번 설치한다.
- 설치 및 렌더 실패 시 확인 가능한 오류 메시지를 전달한다. 완료하지 않은 파일이 있는 척하지 않는다.
- 추가 유료 API, 외부 저작권 미확인 음악, 임의 웹 이미지/폰트 다운로드 금지. 제공된 사진은 편집용으로만 사용하고 출처를 영상에 표기한다.

## 작업 순서 (Codex가 직접 수행)

1. **사용 환경 확인**: 터미널 실행이 가능한 로컬 Codex인지 클라우드 Codex인지 확인한다. 클라우드에서는 사용자의 맥 바탕화면에 바로 저장할 수 없으므로 프로젝트 `output/`에 저장해 파일을 전달한다. 로컬 맥이면 기본값이 `~/Desktop/Sacheon_Airshow_2026/`이다.
2. **환경 준비**: 우선 `python3`, `ffmpeg`, `ffprobe` 확인. Pillow가 빠졌을 때만 `scripts/setup.sh`를 실행한다. 설치 실패 시 필요한 명령을 안내하고 멈춘다. **PyTorch/Node.js/Remotion/edge-tts 설치하지 말 것**(사용자가 별도 요청했을 때만 검토).
3. **사진 준비**: 로컬 사진 경로가 주어지면 `--photos <사진 폴더>`로 직접 읽는다. 없다면 `assets/demo_photos`의 **축소된 원본 예시 사진 12장**으로 시험한다. 원본 사진을 원본 경로에서 복사·이동·삭제하지 않는다. 필요하면 입력 이미지 목록용 `input/manifest.json`을 작성한다. 작성 예시는 `assets/manifest.example.json`.
4. **짧게 테스트**: 우선 아래 6초 미리보기를 렌더링한다. 결과 이미지/동영상과 `render_report.json`을 확인하고 나서만 60초 전체를 실행한다. 장면마다 샘플 1초씩 보여주는 6초 미리보기다.
5. **전체 제작**: 60초 전체 1800프레임, FFmpeg 인코딩, 음향 자동 합성(무음 원하면 `--mute`), 썸네일 생성, `ffprobe` 검증까지 자동 실행한다.
6. **보고**: MP4 절대경로, 길이, 해상도, 사진 수, KF-21 사진명 검증 여부, 출처, 실패/수정 여부, `render_report.json`을 요약한다. Mac 로컬에서는 결과물이 바탕화면 폴더에 생성된다. 결과물을 전달할 수 없는 작업 환경에서는 정확한 경로 및 로컬 실행 명령을 제공한다.

### 실행 명령

현재 스킬의 루트 폴더를 `$SKILL_DIR`로 놓는다(실제 설치 경로로 바꿔 사용).

```bash
# 최초 1회 준비: 설치 가능한 무료 필수 도구만 확인/설치
bash "$SKILL_DIR/scripts/setup.sh"

# 6초, 640×360 테스트. 실제 사진 폴더를 받았다면 --photos 인자를 붙인다.
python3 "$SKILL_DIR/scripts/render.py" --preview --photos "/path/to/photos" \
  --manifest "/path/to/manifest.json"

# 검증 후 60초, 1920×1080 결과물. 둘 다 선택 사항인 옵션임.
python3 "$SKILL_DIR/scripts/render.py" --full --photos "/path/to/photos" \
  --manifest "/path/to/manifest.json"
```

- `--photos`가 없으면 내장 시연 사진 자동 사용.
- `--manifest`가 없으면 기종명을 추정하지 않는 안전 모드.
- 명시적인 출력 폴더: `--output-dir "/path/to/output"`.
- 적은 메모리로 빠르게 확인: `--preview --preset ultrafast`.
- 소리 없이: `--mute` (내레이션은 원래 없음).
- `pip` 설치를 시스템 전역에 무작정 하지 않는다. `scripts/setup.sh`는 `.venv`를 스킬 폴더에 만들고, 명령이 끝나면 그 파이썬 경로를 안내한다. 필요하면 `<스킬>/.venv/bin/python`으로 렌더한다.

## 고정 스토리보드

세부 구성은 `references/storyboard.md`를 읽는다. 총 길이는 정확히 60초.

- 00–08 **INTRO**: 윤곽 스캔과 그리드, `하늘을 설계하다` 타이틀
- 08–20 **KF-21**: 확인된 KF-21 이미지가 있을 때만 `KF-21 BORAMAE`, 아니면 `AIRCRAFT`로 대체. 사진 카메라 이동 + HUD
- 20–32 **AIRCRAFT**: 실제 항공기 사진을 가로 3분할 카드로 노출
- 32–44 **BLACK EAGLES**: 편대비행 사진 위 추상적 장식 궤적 모션(실제 항적 묘사 아님)
- 44–54 **HIGHLIGHT**: 좌우 분할과 빠른 컷, PRECISION / POWER / FLIGHT
- 54–60 **ENDING**: 넓은 사진, `2026 SACHEON AIRSHOW`, `PHOTO BY AJP YOO NA-HYUN`

## 결과와 품질 점검

- `sacheon_airshow_2026_youtube.mp4`
- `sacheon_airshow_thumbnail.jpg`
- `contact_sheet.jpg`
- `render_report.json` (ffprobe의 실제 출력으로 길이/화면 검증)
- `preview_6s.mp4` (사전 시험 때 생성)

매 작업마다 **사진 속 기종 표기가 실제 사진과 일치하는지** 검토한다. 이미지에서 기체가 너무 작거나 확인 불가하면 KF-21 자막을 끄고 사용자에게 사진 검증 필요를 보고한다. 원본 파일을 수정하지 않고 결과물 폴더에만 출력한다.

### 문제 해결

- `Data cannot be cloned, out of memory`: 사진 다량을 Codex 채팅 첨부로 전송하지 말고 한 폴더로 정리해 로컬 경로를 전달한다. 작업 지시도 짧게 보낸다.
- `ffmpeg not found`: macOS에서 `brew install ffmpeg`. 자동 준비 스크립트가 설치 가능 여부를 검사한다.
- `PIL not found`: `bash scripts/setup.sh` 후 만들어진 `.venv/bin/python` 사용.
- 한국어 폰트 깨짐: macOS 기본 한국어 시스템 폰트 사용. 렌더러가 한글 폰트를 못 찾으면 `Noto Sans CJK` 등 시스템에서 사용 가능한 폰트를 찾아 설정한다. **폰트 파일을 배포하거나 무단 다운로드하지 않는다.**
- CPU 렌더 시간이 길면 프리뷰를 먼저 완료하고 최종 작업을 수락한 환경에서 실행한다. 마무리 전에는 `SUCCESS`와 `ffprobe` 검증을 반드시 확인한다.
