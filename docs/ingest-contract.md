# /ingest/* 계약서 — 입력 파트

> 대상: 도영(프론트) · 관호(승인 플로우)
> 담당: 준혁 · 최종 수정 2026-08-25
> 이 문서는 `docs/AskBuddy_개발가이드.md` 6-1 을 구체화한 것이다. 충돌하면 개발가이드가 정본이다.

---

## 1. 확정한 것 두 가지

개발가이드에 비어 있던 항목이다. 아래대로 확정한다.

| 항목 | 결정 |
|---|---|
| Storage 버킷 | **`sources`**, 비공개. `python scripts/init_storage.py` 로 각자 생성 |
| 오브젝트 경로 | `{store_id}/{voice\|video\|kakao\|scan}/{uuid}.{ext}` — **API 가 만들어 준다** |
| `content_hash` | **프론트가 계산해서 보낸다.** 안 보내면 서버가 처리 중에 뒤늦게 채운다 |

원본 파일명은 경로에 남기지 않는다. 한글·공백 파일명이 URL 인코딩에서 깨지고,
같은 이름 재업로드가 서로 덮어쓰기 때문이다.

---

## 2. 업로드 3단계

브라우저는 Supabase 키를 갖지 않는다(불변식 1·2). API 가 1회용 서명 URL 을 발급하고,
파일 바이너리는 API 를 거치지 않고 브라우저에서 Storage 로 직접 간다.

```
① POST /ingest/upload-url   → { upload_url, file_url }
② PUT  <upload_url>          (브라우저 → Storage, 인증 헤더 없음)
③ POST /ingest/sources      → { source_id }
④ POST /ingest/process
⑤ GET  /ingest/status        2초 간격 폴링
```

### 프론트 코드

```ts
const BASE = process.env.NEXT_PUBLIC_API_URL!

export async function uploadVoice(file: File, token: string) {
  const auth = { Authorization: `Bearer ${token}` }

  // ① 서명 URL
  const { upload_url, file_url } = await post('/ingest/upload-url', auth, {
    source_type: 'VOICE',
    filename: file.name,          // 확장자 판별에만 쓰인다
  })

  // ② Storage 로 직접 업로드 — 여기에는 토큰을 붙이지 않는다
  const up = await fetch(upload_url, {
    method: 'PUT',
    headers: { 'content-type': file.type || 'application/octet-stream' },
    body: file,
  })
  if (!up.ok) throw new Error(`업로드 실패: ${up.status}`)

  // ③ 등록 — content_hash 는 여기서 보낸다
  const buf = await file.arrayBuffer()
  const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buf))]
    .map(b => b.toString(16).padStart(2, '0')).join('')

  const { source_id, duplicate } = await post('/ingest/sources', auth, {
    source_type: 'VOICE',
    file_url,                     // ①에서 받은 값을 그대로
    title: file.name,
    file_size: file.size,
    content_hash: hash,
    meta: { audio_format: 'm4a', record_method: 'UPLOAD' },
  })
  if (duplicate) return { source_id, duplicate: true }   // 이미 올린 파일

  // ④ 처리 시작
  await post('/ingest/process', auth, { source_id })
  return { source_id, duplicate: false }
}
```

`crypto.subtle` 은 **HTTPS 또는 localhost 에서만** 동작한다. 배포 후 http 로 열면
여기서 조용히 터지므로, 실패 시 `content_hash` 를 빼고 보내도 등록은 된다.
그 경우 중복 방지는 서버가 처리 중에 뒤늦게 걸어준다.

### 폴링

```ts
const id = setInterval(async () => {
  const s = await get(`/ingest/status?source_id=${sourceId}`, auth)
  if (s.status === 'DONE')   { clearInterval(id); goPreview(s.card_count) }
  if (s.status === 'FAILED') { clearInterval(id); showError(s.error_message) }
}, 2000)
```

**`FAILED` 분기를 빼먹으면 데모에서 스피너가 영원히 돈다.** `error_message` 는 항상 채워진다.

---

## 3. 엔드포인트

모든 요청에 `Authorization: Bearer <JWT>` 가 필요하다.
`store_id` 는 토큰에서만 꺼낸다 — 본문에 넣어도 무시된다(D1).

### POST /ingest/upload-url

```jsonc
// 요청
{ "source_type": "VOICE", "filename": "매장 안내 녹음.m4a" }

// 응답 200
{
  "upload_url": "http://127.0.0.1:54321/storage/v1/object/upload/sign/sources/1/voice/872cfe….m4a?token=…",
  "file_url":   "sources/1/voice/872cfe0605b44234b65b056ead857072.m4a"
}
```

허용 확장자 — 다른 값은 422.

| source_type | 확장자 |
|---|---|
| `VOICE` | `mp3` `m4a` `wav` |
| `VIDEO` | `mp4` `mov` |
| `KAKAO` | `txt` `zip` |
| `SCAN` | `pdf` `jpg` `jpeg` `png` |

### POST /ingest/sources → 201

```jsonc
{
  "source_type": "VOICE",
  "file_url": "sources/1/voice/872cfe….m4a",   // upload-url 응답 그대로
  "title": "오픈 준비 설명",                     // 선택
  "file_size": 1048576,                        // 선택
  "content_hash": "<sha256 hex>",              // 권장
  "meta": { "audio_format": "m4a", "record_method": "UPLOAD" }
}
// → { "source_id": 12, "status": "UPLOADED", "duplicate": false }
```

`meta` 는 유형별로 다르다. `VOICE`·`VIDEO`·`SCAN` 은 필수다.

| source_type | meta |
|---|---|
| `VOICE` | `audio_format` (필수), `record_method`, `duration_sec`, `sample_rate` |
| `VIDEO` | `video_format` (필수), `duration_sec`, `resolution`, `fps` |
| `KAKAO` | `import_type`, `room_name` |
| `SCAN` | `doc_type` (필수), `doc_category`, `page_count` |

`duplicate: true` 면 새 행을 만들지 않고 기존 `source_id` 를 돌려준다.
"이미 올린 파일입니다" 를 띄우고 그 자료의 상태로 넘어가면 된다.

### POST /ingest/process

```jsonc
{ "source_id": 12, "force": false }
```

이미 `PROCESSING` 이거나 `DONE` 이면 다시 돌리지 않고 현재 상태를 돌려준다.
다시 돌리려면 `force: true`.

### GET /ingest/status?source_id=12

```jsonc
{
  "source_id": 12,
  "status": "DONE",              // UPLOADED | PROCESSING | DONE | FAILED
  "error_message": null,         // FAILED 면 반드시 채워짐
  "processed_at": "2026-08-25T07:12:33.120441+00:00",
  "card_count": 3
}
```

### POST /ingest/embed?card_id=42 — 관호님

**점주 승인 직후 호출한다.** 이걸 안 부르면 승인해도 검색에 안 걸린다.

- 승인 안 된 카드 → `409`
- 다른 매장 카드 → `404`

---

## 4. 에러

| 코드 | 언제 |
|---|---|
| 401 | 토큰 없음·만료·서명 불일치 |
| 403 | 토큰에 `store_id` 가 없음 |
| 404 | 남의 매장 자료거나 없는 자료 |
| 409 | 미승인 카드를 임베딩하려 함 |
| 422 | 확장자 불일치, `meta` 형태 불일치 |
| 502 | 서명 URL 발급 실패 (`SUPABASE_SERVICE_KEY` 확인) |

---

## 5. 추출된 카드

`DONE` 이후 카드는 **전부 `is_verified = false`** 다. 점주 검수를 통과해야 검색에 노출된다.

- `confidence` 는 DB 에 0~100 으로 저장된다 (0~1 아님)
- **60 미만은 검수 화면 상단에 우선 노출한다** (D3)
- 카드 조회는 관호님 `/reg/cards` 를 쓴다

---

## 6. M1 동안 알아둘 것

`INGEST_MODE=mock` 이 기본값이라 **LLM 키 없이** 전 구간이 돈다.
목 추출기가 카드 3건을 넣고, 그중 하나는 `confidence 42.0` 이다.
검수 화면의 "우선 노출" 분기를 실제로 렌더해보라고 일부러 넣었다.

목 모드에서는 파일을 실제로 내려받지 않으므로, ②단계를 건너뛰고
`file_url` 에 아무 문자열이나 넣어도 `DONE` 까지 간다.

로그인이 붙기 전까지 토큰은 이렇게 만든다.

```bash
cd api && export ASKBUDDY_TOKEN=$(./.venv/bin/python scripts/dev_token.py)
```
