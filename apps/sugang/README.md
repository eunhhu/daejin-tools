# Sugang — 기존 수강 도구

저장소 루트에 있던 기존 수강 관련 코드를 이 디렉터리에 모았습니다.
Python 소스의 동작은 변경하지 않았으며, CLI·GUI·웹 옵저버 사이의 기존 파일 배치도 유지합니다.

> **운영 중지.** 이 문서는 재가동 안내가 아닙니다. 기존 자동조회·자동신청 서비스를
> 시작하거나 등록하지 마세요. 실제 학교 시스템을 이용하는 검증은 별도 허가가 필요합니다.

## 파일 경계

- `sugang.py`, `query_courses.py`: 기존 CLI.
- `gui_qt.py`: 기존 Qt 데스크톱 UI.
- `web_observer.py`, `push_manager.py`: 기존 웹 옵저버·알림 코드.
- 나머지 Python 스크립트: 보존한 수강 관련 레거시 도구.
- `manifest.json`, `sw.js`, `targets.json`: 앱 전용 정적 리소스와 설정 목록.
- `config.example.json`: 형식 참고용 예제. 실제 자격증명은 포함하지 않습니다.
- `requirements.txt`: 기존 CLI/브라우저 도구 의존성.
- `requirements-web.txt`: 웹 모듈 및 오프라인 회귀 테스트 의존성.

## 오프라인 테스트

저장소 루트에서 실행합니다.

```bash
python -m pip install -e ".[dev]" -r apps/sugang/requirements-web.txt
python -m pytest tests/sugang -q
```

테스트는 원본 스크립트를 임시 폴더에 복사하고 빈 설정을 사용합니다.
`config.json`, 푸시 키, 캐시를 저장소에 만들거나 실제 서비스에 연결하지 않습니다.

기존 스크립트 중에는 import 시 설정을 읽고 키 파일을 생성하는 코드가 있습니다.
따라서 **공통 패키지에서 이 모듈들을 import하지 않습니다.**
이 동작을 없애는 내부 리팩터링은 이번 파일 이동과 분리한 후속 작업입니다.

기존 상대경로·설정 위치와 릴리스 태그 변경은 [이전 안내](../../docs/migration.md)를 참고하세요.
