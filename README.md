# Daejin Tools

대진대학교 생활·학사 도구를 기능별로 모으는 **비공식 프로젝트**입니다.
기존 `daejin-sugang`을 `daejin-tools`로 변경하고, 수강신청 코드를 독립된 앱으로 분리했습니다.

> **운영 상태:** 기존 수강 자동조회·자동신청 서비스는 중지 상태입니다.
> 저장소 설치, 테스트, 빌드는 서비스를 시작하지 않습니다. 학교 시스템을 대상으로 한
> 자동조회나 운영 재개는 별도 허가·검토 없이 진행하지 않습니다.

## 구조

```text
daejin-tools/
├── apps/
│   ├── sugang/              # 기존 수강 도구와 전용 리소스
│   └── library/             # 접속 시 조회하는 도서관 예약실 시간표
├── src/
│   └── daejin_tools/        # 공통 Python 코드용 네임스페이스
├── tests/
│   ├── sugang/              # 계정 없이 실행하는 기존 기능 회귀 테스트
│   ├── library/             # 오프라인 파서·캐시·API·브라우저 테스트
│   └── test_*.py            # 저장소 경계·공통 패키지 테스트
├── deploy/
│   └── sugang/              # 기존 배포 참고 파일 (자동 적용 안 함)
├── docs/                    # 구조·이전 안내
├── pyproject.toml           # 패키지 메타데이터·개발 도구 설정
└── .github/workflows/       # 오프라인 테스트 및 빌드 CI
```

- **도서관 시간표:** [apps/library](apps/library/README.md) — 방문 시에만 조회, 자동 갱신 없음
- **기존 수강 코드:** [apps/sugang](apps/sugang/README.md)
- **새 기능 추가:** [기여 안내](CONTRIBUTING.md) · [아키텍처](docs/architecture.md)
- **기존 경로에서 이전:** [마이그레이션 안내](docs/migration.md)

아직 구현하지 않은 학사 기능의 빈 모듈은 만들지 않습니다. 다음 기능부터
`apps/<기능명>/`에 추가하고, 실제로 여러 앱이 공유하는 Python 코드만
`src/daejin_tools/`로 추출합니다. 공통 패키지는 현재 네임스페이스만 제공하며
수강 앱을 포함하거나 실행하지 않습니다.

## 개발 환경

Python **3.11 이상**을 사용합니다.

```bash
git clone https://github.com/eunhhu/daejin-tools.git
cd daejin-tools
python -m venv .venv
```

환경 활성화: Linux/macOS는 `source .venv/bin/activate`, Windows PowerShell은
`.venv\Scripts\Activate.ps1`을 사용합니다.

```bash
python -m pip install -e ".[dev]" -r apps/sugang/requirements-web.txt -r apps/library/requirements.txt
python -m pytest -q
python -m ruff check src tests apps/library
npm ci
npm test
python -m build
```

테스트는 수집 단계부터 소켓 사용을 차단합니다. 기존 수강 모듈은 임시 디렉터리로
복사하여 빈 테스트 설정으로 로드하며, 실제 계정·캐시·푸시 키를 사용하지 않습니다.
GUI·브라우저 실행, 실제 수강신청, 서버 기동은 이 검증에 포함하지 않습니다.

`python -m build`의 wheel/sdist는 **공통 Python 패키지** 산출물입니다.
수강 GUI 실행 파일이나 전체 도구 모음 설치 프로그램은 아닙니다.

## CI와 배포 경계

- 일반 push/PR: Linux·Windows·macOS에서 테스트, 린트, 공통 패키지 빌드 및 설치 검증.
- 기존 수강 GUI 릴리스: `sugang-v*` 전용 태그 또는 수동 워크플로우만 사용.
- 일반 `v*` 태그로 수강 GUI를 배포하지 않습니다.
- CI에서 학교 API 조회, 옵저버 실행, systemd 변경, 운영 배포를 하지 않습니다.
- 수강 앱 내부는 보존한 레거시 코드입니다. 이번 구조 정리는 내부 로직 전체의 안전성,
  실제 서비스 가동, GUI 동작을 새로 보증하는 작업이 아닙니다.
