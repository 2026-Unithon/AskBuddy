# API 무중단 배포 계획

2026-10-03 · 상태: **방법 정리만. 구현 보류.** 지금은 배포 때 몇 초 끊기는 것을 받아들인다(차준혁 결정).
선행 문서: [API 자동 배포 설계](API_AUTO_DEPLOY_DESIGN.md), [운영 접속 설정](../DEPLOY_ACCESS_SETUP.md).

## 1. 결론

- **쿠버네티스·EKS·ECS 없이 서버 한 대로 된다.** 이 도구들은 서버 여러 대, 자동 확장, 노드 교체가 필요할 때 쓴다.
  EKS는 관리비만 월 70달러 이상이고, 지금 트래픽과 운영 인력에 비해 관리 부담이 크다.
- 순서는 **①이미지 미리 빌드 → ②새 컨테이너가 준비된 뒤 옛 것을 내림 → ③진행 중 작업을 끝내고 내림**이다.
  ①만으로도 배포 시간과 디스크 문제가 크게 줄고, ②를 더해야 끊김이 사라진다.

## 2. 지금 끊기는 이유

현재 서버 배포(`deploy/remote_deploy.sh`)는 `docker compose up -d --build` 한 번이다.

| 구간 | 상태 |
|---|---|
| 서버에서 이미지 빌드 (수 분) | 옛 컨테이너가 계속 응답한다 |
| 옛 컨테이너 중지 → 새 컨테이너 생성·기동 (수 초) | **응답 없음.** Caddy가 502를 돌려준다 |
| 새 컨테이너 기동 완료 | 정상 |

함께 생기는 문제는 이렇다.
- **서버 빌드:** t4g.small(ARM, 메모리 2GB, CPU 2개)에서 빌드하면 느리고, 빌드 캐시가 디스크를 채운다. 2026-10-03에 8GB 디스크가 가득 차 SSM 접속과 서비스가 모두 멈췄다.
- **진행 중 작업:** 컨테이너를 내리면 그 안에서 돌던 작업이 함께 끊긴다(§4-2).

## 3. 단계

### ① 이미지를 GitHub에서 빌드해 받아 온다

**바꾸는 것**
- `deploy-api.yml`에 빌드 job을 추가한다. arm64 이미지를 만들어 `ghcr.io/2026-unithon/askbuddy-api:<커밋 SHA>`로 올린다.
  - runner: 공개 저장소는 `ubuntu-24.04-arm` runner를 무료로 쓸 수 있다. 서버와 같은 arm64라 에뮬레이션이 필요 없다.
  - 권한: `packages: write`. 이미지에 비밀값이 들어가지 않는지 확인한다. 지금 Dockerfile은 env 파일을 복사하지 않는다.
- `deploy/compose.yml`의 `build: ../api`를 `image: ghcr.io/2026-unithon/askbuddy-api:${API_IMAGE_TAG}`로 바꾼다.
- `remote_deploy.sh`를 `docker compose pull api && docker compose up -d`로 바꾼다. 서버에서 빌드하지 않는다.
- 배포 순서는 **빌드·push 성공 → 백업 → migration → 서버 pull·교체 → health**다. 빌드가 실패하면 DB를 건드리지 않는다.

**정할 것**
- GHCR 패키지 공개 여부. 공개면 서버가 로그인 없이 받는다. 비공개면 서버에 읽기 전용 토큰을 둬야 한다.
  저장소가 이미 공개라 코드 노출 차이는 없다. 이미지에 비밀값이 없는지만 확인되면 공개가 단순하다.
- 이미지 보관 개수. 오래된 태그를 정리하는 규칙을 둔다(예: 최근 20개).

**효과**
- 서버 배포가 수 분에서 수십 초로 준다. 디스크에 빌드 캐시가 쌓이지 않는다.
- 이전 커밋 이미지가 남아 있어 되돌리기가 `API_IMAGE_TAG`만 바꾸는 일이 된다.
- **끊기는 몇 초는 그대로다.** ②가 필요하다.

### ② 새 컨테이너가 준비된 뒤 옛 것을 내린다

방법은 두 가지다. **A를 먼저 시도한다.**

**A. docker rollout 플러그인** (권장)
- 하는 일: api를 잠시 2개로 늘리고, 새 컨테이너의 healthcheck가 통과하면 옛 컨테이너를 내린다.
- 필요 조건: api 서비스에 `container_name`과 외부 `ports`가 없을 것. 지금 구성이 이미 그렇다.
- compose에 healthcheck를 추가한다. 이미지에 curl이 없으면 Python으로 확인한다.
  ```yaml
  healthcheck:
    test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
    interval: 5s
    timeout: 4s
    retries: 12
  ```
- `remote_deploy.sh`: `docker compose pull api && docker rollout api`. caddy는 바뀔 때만 `docker compose up -d caddy`로 한다.
- Caddy 설정: 교체 순간 옛 컨테이너로 가던 요청이 실패하지 않게 재시도 시간을 준다.
  ```
  api.askbuddy.kr {
      reverse_proxy api:8000 {
          lb_try_duration 10s
          lb_try_interval 250ms
      }
  }
  ```
  Caddy가 `api` 이름을 매번 다시 조회해 두 컨테이너 중 살아 있는 쪽으로 붙는지 **실측으로 확인한다.**
  안 되면 `dynamic a api 8000` upstream으로 바꾼다.

**B. 고정 2개 + Caddy 로드밸런싱** (A가 안 될 때)
- 하는 일: `api_blue`, `api_green` 두 서비스를 상시 띄우고, Caddy가 `health_uri /health`로 살아 있는 쪽에만 보낸다. 배포는 하나씩 번갈아 교체한다.
- 단점: 메모리를 상시 두 배로 쓴다. 2GB 서버에서는 §4-1 확인 결과가 넉넉해야 한다.

### ③ 진행 중 작업을 끝내고 내린다

- `docker stop`은 기본 10초 뒤 강제 종료한다. 업로드 추출처럼 수 분 걸리는 작업이 끊긴다.
- compose `stop_grace_period`를 늘린다(예: 10m). uvicorn은 종료 신호를 받으면 새 요청을 받지 않고 진행 중 요청을 마친 뒤 내려간다.
- 다만 업로드 추출·재분류는 요청 응답 뒤 같은 프로세스의 백그라운드 작업으로 돈다. uvicorn이 이 작업을 끝까지 기다리는지 **먼저 실측한다.**
  기다리지 않으면 이 작업들을 lease 기반 worker로 옮기는 별도 설계가 필요하다(§6).

## 4. 시작 전 확인

### 4-1. 메모리
api 두 개가 동시에 뜰 수 있는지 본다. rollout 중 수십 초, B 방식이면 상시다.
```bash
free -m
docker stats --no-stream
```
api 한 개 상주 메모리 × 2 + caddy + OS 여유가 2GB 안에 들어와야 한다. 빠듯하면 스왑 1~2GB를 추가하거나 인스턴스 크기를 올린다.

### 4-2. 두 컨테이너가 잠깐 동시에 돌아도 안전한가

| 서버 안 작업 | 동시 실행 | 근거 |
|---|---|---|
| 지난 진단 기록 정리(1시간 주기) | 안전 | 같은 정리를 두 번 해도 결과가 같다 |
| 점주 답변 반영 worker | 안전 | 작업마다 DB lease·heartbeat를 잡는다. 여러 worker를 전제로 설계됐다 |
| 점주 알림 outbox 소비 | 안전 | 행 잠금(`for update skip locked`)으로 한 건을 한 곳만 가져간다 |
| 업로드 추출·재분류 | **확인 필요** | 요청을 받은 컨테이너 안에서만 돈다. 동시 실행 자체는 문제없지만, 옛 컨테이너가 내려갈 때 끊긴다(§3-③) |

이 표는 2026-10-03 코드 기준이다. 서버 안에 주기 작업을 새로 추가하면 이 표를 갱신한다.

### 4-3. DB 구조 변경 호환
무중단은 **옛 코드와 새 코드가 같은 DB에서 잠깐 함께 돈다**는 전제다. 이미 팀 규칙이다.
- 추가형 변경(테이블·컬럼 추가, 제약 완화)만 한 번에 올린다.
- 삭제·이름 변경은 "코드에서 사용 중단 배포 → 다음 배포에서 삭제"로 나눈다.

## 5. 검증

배포하는 동안 다른 터미널에서 1초마다 요청을 보내 실패가 0건인지 본다.
```bash
while true; do
  printf '%s ' "$(date +%T)"
  curl -s -o /dev/null -w '%{http_code}\n' --max-time 3 https://api.askbuddy.kr/health
  sleep 1
done
```
- ②까지 적용한 뒤 기준: 배포 중 200이 아닌 응답이 0건이다.
- ③ 기준: 업로드 추출을 시작한 직후 배포해도 작업이 `FAILED`로 끝나지 않는다.

## 6. 하지 않는 것과 나중 과제

- **쿠버네티스·ECS 전환:** 서버 2대 이상, 자동 확장, 다른 지역 이중화가 필요해질 때 다시 검토한다.
- **DB 무중단 구조 변경 도구:** 지금 규모에서는 팀 규칙으로 충분하다.
- **업로드 추출을 별도 worker로 분리:** ③ 실측에서 uvicorn이 백그라운드 작업을 기다리지 않으면 필요하다.
  작업을 DB 대기열에 넣고 lease로 가져가는 구조다. 점주 답변 worker와 같은 방식이다.
- **배포 실패 알림 강화:** 지금은 GitHub 기본 이메일뿐이다.
