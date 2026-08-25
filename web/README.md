# web — Next.js 16 (도영, `feat/output`)

아직 Next 프로젝트가 생성되지 않았다. 이 폴더에는 `.env.example` 만 있다.

## 스캐폴딩

`create-next-app` 은 대상 폴더에 `.env.example` 이 있으면 "conflicting files" 로 멈춘다.
잠깐 비켜뒀다가 되돌린다.

```bash
mv web/.env.example /tmp/askbuddy.env.example
pnpm create next-app@latest web --ts --app --tailwind --eslint --no-src-dir --import-alias "@/*"
mv /tmp/askbuddy.env.example web/.env.example

cd web
cp .env.example .env.local
pnpm dev            # http://localhost:3000
```

생성 후 만들 것:

```
web/
├─ app/             # 화면. welcome → role-select → owner|staff 흐름
├─ components/      # ver2 프로토타입에서 이식
├─ lib/api.ts       # FastAPI 호출 래퍼 — 모든 데이터 접근은 여기를 통과한다
└─ types/           # supabase gen types 산출물 (응답 타입 재사용용)
```

## 이 폴더에서 하지 말 것

- Supabase 클라이언트 설치 (불변식 1 — 브라우저는 DB를 직접 치지 않는다)
- `OPENAI_API_KEY`·`GEMINI_API_KEY`·`SUPABASE_SERVICE_KEY` 배치 (불변식 2·3)
- `kind: "miss"` 응답에 LLM 으로 문장 만들기 → "사장님께 확인 중" 배지만
- 폴링에서 `FAILED` 분기 누락 → 데모에서 스피너가 영원히 돈다
