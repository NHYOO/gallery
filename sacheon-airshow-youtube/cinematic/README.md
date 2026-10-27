# ZIP 통합 제작 코드

이 폴더는 sacheon-cinematic-trailer.zip을 실제 사진·캐릭터와 통합한 모듈입니다.
현재 결과는 한국어 내레이션 없는 임시본이며 음악과 효과음이 포함됩니다.
1920×1080·30fps, 후속 실제 발화 타임스탬프 자막 경로를 사용합니다.
전체 안내·결과 파일·재실행·음성 추가 명령은 상위 CINEMATIC_README.md를 읽으세요.
기존 AI_SCENE_PROMPTS.md와 CODEX_PROMPT.md는 원본 ZIP 참고자료입니다.
실제 실행은 ../scripts/render_cinematic.py --preview --temporary 또는 --temporary.
음성 추가 시 --narration AUDIO --alignment-json JSON 또는 명시적 --transcribe를 사용합니다.
--transcribe에는 별도 API 키·네트워크·과금이 필요합니다.
