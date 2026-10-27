# Codex에 붙여 넣을 작업 지시문

이 폴더의 `README.md`, `storyboard.json`, `trailer.py`,
`assets/README.md`를 먼저 모두 읽어줘.

내가 넣은 2026 사천에어쇼 실제 취재 사진을 우선 사용해 영화 예고편처럼
연출한 **60초, 1920×1080, 16:9, 24fps MP4**를 제작해줘.
내레이션은 중학생(13~15세)이 미래 조종사를 꿈꾸며 말하는 1인칭이고,
자막·대사·시네마틱 음악·전환 효과음이 반드시 들어가야 해.

진행 순서:

1. `storyboard.json`에 지정된 8개 장면의 실제 파일 존재 여부를 확인.
2. 실사 보도 사진은 원본 기체와 사건 내용이 바뀌지 않게 움직임만 부여.
   2036 조종석과 미래 무인기 구상 등은 AI로 만들어도 되며, 보도 사진과
   혼동되지 않도록 영상에 'AI 연출 / 미래 구상'을 표시.
3. TTS 사용이 가능하면 장면별 한국어 내레이션 생성. 키가 없으면 먼저
   Mac 한국어 음성 또는 제공된 WAV 파일을 활용. API 키를 응답에 출력하지 말 것.
4. `python3 trailer.py --demo --preview --draft`로 렌더링 기능을 점검한 뒤,
   실제 미디어로 `python3 trailer.py --preview --tts auto` 실행.
5. 6초 테스트를 검수한 뒤 `python3 trailer.py --tts auto`로 최종 출력.
6. ffprobe로 길이 60초·1920×1080·오디오 포함을 확인하고,
   자막 화면을 실제 프레임으로 살펴 한글 깨짐·오버플로가 없는지 검수.
7. 완성한 MP4와 별도 자막 SRT를 다운로드 가능한 경로로 제공.

음악은 저작권 문제가 없는 원본 또는 사용 허락을 받은 트랙만 사용해줘.
기본 임시 합성 음악은 필요한 경우 사용할 수 있지만, 과한 효과보다
장면별 호흡과 실제 항공기 소리의 현장감을 중요하게 다뤄줘.

사실관계:
- https://www.ajunews.com/view/20261023150655387
- https://www.dapa.go.kr/dapa/doc/selectDoc.do?bbsSeq=326&docSeq=59188&menuSeq=3069
- https://www.dapa.go.kr/dapa/doc/selectDoc.do?bbsSeq=326&docSeq=58922&menuSeq=3069
- https://www.koreaaero.com/KO/Business/KF21.aspx

이전에 만든 `SKILL.md`와 `VIDEO_BRIEF.md`가 같은 Codex 프로젝트 안에
있다면 두 파일도 **함께 읽고**, 상충되는 구체적 렌더링 설정은
이번 `storyboard.json`과 사용자 최신 지시를 우선해줘.
