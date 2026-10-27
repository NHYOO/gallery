# 2026 사천에어쇼 — 시네마틱 임시본

ZIP의 영상·전환 함수를 기존 제작 코드와 통합했습니다. 현재 결과는 **한국어
내레이션이 없는 임시본**이며 음악·효과음은 포함됩니다. 영상 상단과 파일명의
`TEMP`가 이를 표시합니다.

## 제작물

`output/cinematic/`에 아래 파일이 있습니다.

- `sacheon_trailer_6s_TEMP_1080p.mp4`: 먼저 렌더링·검수한 6초 테스트
- `sacheon_trailer_60s_TEMP_1080p.mp4`: 60.000초·1920×1080·16:9·30fps·H.264
- `captions_6s_TEMP.srt`, `captions_60s_TEMP.srt`: 한국어 가안 자막
- `verification_6s_TEMP.json`, `verification_60s_TEMP.json`: 실제 FFprobe·디코딩·음량 검사
- `narration_script.txt`: 녹음용 대사와 편집 슬롯
- `contact_sheet.jpg`: 실제 렌더 프레임 검수표

오디오는 AAC·48kHz·스테레오입니다. 코드로 화성·스트링형 펄스·드럼·잔향을
만들고 제트 엔진·비행·전환 효과를 합성했습니다. 현장 녹음·외부 상업 음악·음악
생성 AI를 사용하지 않았습니다. 원본 사진·캐릭터는 수정하거나 삭제하지 않으며,
렌더 전후 SHA-256을 비교합니다.

## 재실행

저장소 루트 `gallery/`에서 실행합니다. Python·FFmpeg/FFprobe·Pillow·NumPy·SciPy가
필요합니다. 동봉 Noto Sans KR의 OFL 라이선스를 보존합니다. 중간 파일은 `work/`에
생성됩니다.

```bash
python3 sacheon-airshow-youtube/scripts/render_cinematic.py --preview --temporary
python3 sacheon-airshow-youtube/scripts/render_cinematic.py --temporary
```

## 실제 한국어 내레이션 추가

현재 TTS 도구·한국어 음성 모델·녹음 파일·API 키가 없어 음성을 만들지 않았습니다.
`narration_script.txt`의 장면 시간에 맞춘 60초 이내 녹음을 준비하세요. 남는 구간은
패딩하며 긴 음성을 임의로 자르거나 속도를 바꾸지 않습니다.

기존 음성 인식 도구에서 실제 발화 구간 JSON을 받았다면 오프라인으로 실행합니다.

```bash
python3 sacheon-airshow-youtube/scripts/render_cinematic.py \
  --narration /path/to/korean_narration.wav \
  --alignment-json /path/to/speech_segments.json
```

JSON 형식은 다음과 같습니다.

```json
{"segments":[{"start":0.6,"end":4.9,"text":"2036년, 상상 속 저는 조종석에 앉아 있어요."}]}
```

실제 녹음 파일에서 타임스탬프를 자동 추출하려면 별도 음성 인식 API를 선택합니다.
`OPENAI_API_KEY`와 `api.openai.com` 네트워크 접근이 필요하며 별도 API 과금이
있을 수 있습니다. 키를 코드·JSON·명령행 인자에 적지 마세요. API는 `--transcribe`를
명시했을 때만 호출합니다.

```bash
python3 sacheon-airshow-youtube/scripts/render_cinematic.py \
  --narration /path/to/korean_narration.wav --transcribe
```

실제 발화 타임스탬프로 SRT·ASS를 만들고 음성·음악을 믹싱해
`sacheon_trailer_60s_narrated_1080p.mp4`를 출력합니다. 타임스탬프가 없거나
입력이 무음이면 실패합니다. ASR 문구·시간은 모델 추정이므로 실제 청취 검수가
필요합니다. 이번 작업에서는 음성 API를 호출하지 않았고 실제 음성 동기를 검증하지
않았습니다. 임시본의 자막 시간은 음성 없는 가안입니다.

## 장면과 출처

- 00–07초: 업로드 캐릭터를 참조한 2036년 상상 속 조종석. `AI 연출` 표시.
- 07–18초: 실제 블랙이글스 취재 사진 4장. 기체·편대·연막 보존.
- 18–41초: KF-21·국산 AESA 레이더·2015 개발 착수·2022 첫 비행 설명 그래픽.
- 41–51초: 유·무인 협업 미래 구상. 실제 운용 장면으로 표현하지 않음.
- 51–56초: 실제 현장 조종사 사진.
- 56–60초: 원본 캐릭터·엔딩·사진 크레딧.

제공된 실제 사진 28장에서 KF-21을 명확히 확인하지 못했습니다. 다른 기종을
KF-21로 표기하지 않고 `KF-21 설명 그래픽 · 자료사진 없음`으로 구분합니다.
검증하지 못한 ZIP의 2026 개발 완료·시험 횟수·인도 시점은 사용하지 않았습니다.

사진: PHOTO BY AJP YOO NA-HYUN. 원본 28장 중 5장 사용.
기사: https://www.ajunews.com/view/20261023150655387
개발 개요 참고: https://www.koreaaero.com/KO/Business/KF21.aspx
이번 환경에서는 위 웹페이지를 직접 읽어 재검증하지 못했습니다.

## 코드

- `scripts/render_cinematic.py`: 통합 제작·자막·믹싱·검증·임시본 표시
- `cinematic/trailer.py`: ZIP의 영상·전환 함수; 직접 실행하면 통합 CLI 연결
- `cinematic/storyboard.json`: 60초 장면·실제 사진 경로·대사
- `cinematic/audio_design.py`: 오리지널 코드 음악·효과음
- `cinematic/narration_sync.py`: 실제 음성·타임스탬프 기반 SRT
- `cinematic/graphics_design.py`: KF-21 설명 그래픽

기존 `scripts/render.py`, `render_framewise.py`와 원본 ZIP은 보존했습니다.

클라우드 제약: 채팅 전용 `/codex/.../output` 경로는 생성·쓰기 권한이 없습니다.
파일은 `/workspace/gallery/sacheon-airshow-youtube/output/cinematic/`에 저장됩니다.
공개 저장소 게시나 외부 업로드는 별도 승인 없이 수행하지 않습니다.
