# Applications

기능별 실행 코드와 전용 리소스는 `apps/<name>/`에 둡니다.

- [`sugang/`](sugang/README.md): 기존 수강신청 관련 코드. 현재 운영 중지.

새 앱은 자기 README, 의존성 정의, `tests/<name>/` 테스트를 함께 추가합니다.
앱끼리 내부 파일을 직접 import하지 않고, 실제 공통 코드만 `src/daejin_tools/`로 옮깁니다.
아직 선택되지 않은 프레임워크나 미래 기능의 빈 디렉터리는 만들지 않습니다.
