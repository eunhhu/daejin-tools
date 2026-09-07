# daejin-sugang → daejin-tools

GitHub 저장소의 이름만 변경했으며 기존 이력과 기본 브랜치 `main`을 유지합니다.
기존 클론의 원격 주소는 다음처럼 갱신할 수 있습니다.

```bash
git remote set-url origin https://github.com/eunhhu/daejin-tools.git
```

## 경로 변경

- 루트의 기존 Python 스크립트 → `apps/sugang/<기존 파일명>`
- `config.example.json`, `targets.json`, `manifest.json`, `sw.js` → `apps/sugang/`
- `requirements.txt` → `apps/sugang/requirements.txt`
- 기존 회귀 테스트 → `tests/sugang/`
- `deploy/daejin-observer.service.d/` → `deploy/sugang/daejin-observer.service.d/`

루트 경로에 자동 실행용 호환 wrapper를 두지 않습니다. 예전 스크립트 경로를 참조하는
외부 도구는 별도 검토가 필요합니다. 스크립트 내부의 파일 상대 위치는 유지하지만,
일부 스크립트가 받는 상대경로 인자는 종전처럼 호출 작업 디렉터리를 기준으로 해석합니다.

`config.json`, 캐시, Web Push 키·구독 정보는 추적하지 않고 이번에 복사하지 않았습니다.
기존 운영 체크아웃, systemd 설정, 프록시 설정, 도메인, 서비스를 변경하거나 재시작하지 않았습니다.
공용 서비스 이름이나 URL을 레포 이름에 맞춰 자동 변경하지도 않습니다.

## 의존성과 테스트

루트는 이제 공통 패키지의 `pyproject.toml`을 사용합니다. 개발 환경 설치 명령은
[README](../README.md#개발-환경)를 참고하세요. 기존 수강 테스트는 pytest의
임시 디렉터리 격리 훅을 사용하므로 `unittest discover` 대신 `python -m pytest`로 실행합니다.

## 릴리스 구분

기존 GUI 워크플로우는 이동한 앱 경로에서 빌드하도록 수정했습니다.
태그 조건은 `v*`에서 **`sugang-v*`**로 좁혔습니다. 일반 프로젝트 태그가
실수로 수강 GUI를 릴리스하지 않게 하기 위함입니다.
기존 GUI 산출물의 `DaejinSugangSuite` 이름은 호환성을 위해 유지합니다.

이번 작업에서 새 태그·GUI 릴리스·운영 배포는 만들지 않습니다.
기존 수강 자동조회·자동신청 운영 중지 상태도 그대로 유지합니다.
