"use client";

import { notFound, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import {
  AnswerBubble,
  Banner,
  ConfirmDialog,
  AskBar,
  BackButton,
  Button,
  Caption,
  CardLink,
  CheckRow,
  Chip,
  Composer,
  ComposerTool,
  Empty,
  ErrorInline,
  HeaderActions,
  HeroCard,
  HeroClock,
  HeroProgress,
  ListGroup,
  ListRow,
  OWNER_TABS,
  PageHeader,
  QuestionBubble,
  Screen,
  SectionTitle,
  Sheet,
  Skeleton,
  STAFF_TABS,
  Stagger,
  SwipeRow,
  TabBar,
  useFeedback,
} from "@/components/kit";
import { useLongPress } from "@/lib/use-long-press";

// 개발 전용: 공통 컴포넌트를 Figma 화면(O6·A2·A5·O9)과 나란히 비교하는 미리보기. ?s=o6|a2|a5|o9|states
function Preview() {
  const screen = useSearchParams().get("s") ?? "o6";
  const [text, setText] = useState("");
  const [checks, setChecks] = useState<boolean[]>([false, false, false]);
  const [sheet, setSheet] = useState(false);

  if (screen === "feedback") return <FeedbackPreview />;
  if (screen === "gestures") return <GesturesPreview />;

  if (screen === "a2") {
    return (
      <Screen tabBar={<TabBar tabs={STAFF_TABS} />}>
        <PageHeader title="오늘 할 일" action={<HeaderActions role="STAFF" />} />
        <HeroCard buddySize={80} className="gap-2">
          <HeroClock pill>미들조 · 14:00–18:00</HeroClock>
          <p className="text-[24px] font-bold tracking-[-0.48px]">{checks.filter((c) => !c).length}개 남았어요</p>
          <div className="w-[200px]">
            <HeroProgress done={checks.filter(Boolean).length} total={checks.length} height={8} label="체크 진행" />
          </div>
        </HeroCard>
        <ul className="flex w-full flex-col rounded-[20px] bg-surface px-[18px] shadow-card">
          {["우유 재고 채우기", "원두 소분", "시럽 보충"].map((label, i) => (
            <CheckRow
              key={label}
              label={label}
              checked={checks[i]}
              onToggle={() => setChecks((prev) => prev.map((c, j) => (j === i ? !c : c)))}
            />
          ))}
        </ul>
        <Button onClick={() => setSheet(true)}>다 했어요</Button>
        <div className="mt-auto">
          <AskBar value={text} onChange={setText} onSubmit={() => setText("")} onVoice={() => undefined} />
        </div>
        <Sheet open={sheet} onClose={() => setSheet(false)} title="알바도 기록으로 남겨요" description="시트 미리보기">
          <Button onClick={() => setSheet(false)}>닫기</Button>
        </Sheet>
      </Screen>
    );
  }

  if (screen === "a5") {
    return (
      <Screen footer={<AskBar value={text} onChange={setText} onSubmit={() => setText("")} onVoice={() => undefined} />}>
        <BackButton parent="/dev/kit" />
        <p className="text-[20px] font-black leading-[1.45] tracking-[-0.4px]">버디</p>
        <QuestionBubble>바닐라라떼 시럽 몇 번?</QuestionBubble>
        <AnswerBubble chips={<Chip>카드 · 바닐라라떼</Chip>}>2펌프예요.</AnswerBubble>
        <QuestionBubble>디카페인 원두 어디 있어요?</QuestionBubble>
        <AnswerBubble chips={<Chip>확인 중 · 답 오면 알려드려요</Chip>}>
          {"아직 매장 카드에 없어요.\n확인 목록에 올려뒀어요. 답이 오면 여기로 와요."}
        </AnswerBubble>
      </Screen>
    );
  }

  if (screen === "o9") {
    return (
      <Screen tabBar={<TabBar tabs={OWNER_TABS} />}>
        <PageHeader title="카드" />
        <ListGroup label="레시피">
          <ListRow title="바닐라라떼 (ICE)" subtitle="시럽 2펌프 · 샷 2개" badge={<Chip size="sm">바뀌었어요</Chip>} href="/dev/kit" />
          <ListRow title="아이스 아메리카노" subtitle="샷 2개 · 얼음 2/3" href="/dev/kit" />
        </ListGroup>
        <ListGroup label="재고 · 위치">
          <ListRow title="디카페인 원두" subtitle="창고 왼쪽 선반 2칸" badge={<Chip size="sm" tone="accent">새 카드</Chip>} href="/dev/kit" />
        </ListGroup>
      </Screen>
    );
  }

  if (screen === "states") {
    return (
      <Screen>
        <PageHeader title="상태" />
        <Skeleton />
        <Skeleton className="h-24" />
        <Empty title="지금은 기다리는 질문이 없어요" description="직원이 물어보면 여기에 와요" />
        <ErrorInline message="지금 내용을 확인하지 못했어요. 다시 시도해주세요." onRetry={() => undefined} />
        <Button loading>저장 중</Button>
        <Button variant="secondary">더 넣기</Button>
        <Button variant="kakao">카카오 로그인</Button>
        <Button variant="danger">지우기</Button>
      </Screen>
    );
  }

  return (
    <Screen
      tabBar={<TabBar tabs={OWNER_TABS} />}
      footer={
        <Composer
          label="새로 알려줄 것"
          value={text}
          onChange={setText}
          onSubmit={() => setText("")}
          placeholder="새로 알려줄 것 넣기"
          tools={
            <>
              <ComposerTool icon="mic" label="말하기" onClick={() => undefined} />
              <ComposerTool icon="camera" label="찍기" onClick={() => undefined} />
              <ComposerTool icon="clip" label="파일" onClick={() => undefined} />
            </>
          }
        />
      }
    >
      <PageHeader eyebrow="더카페 논현점" title="오늘 매장" action={<HeaderActions role="OWNER" />} />
      <HeroCard className="gap-3">
        <HeroClock>지금 · 미들 진행 중</HeroClock>
        <p className="text-[22px] font-bold tracking-[-0.44px]">영업 중이에요</p>
        <div className="flex gap-2 py-1">
          {[
            ["오픈", 7, 7],
            ["미들", 4, 7],
            ["마감", 0, 6],
          ].map(([name, done, total]) => (
            <div key={name as string} className="flex flex-1 flex-col gap-1.5">
              <p className="text-[13px] font-bold tracking-[-0.26px]">
                {name} <span className="text-[12px] font-medium">{done}/{total}</span>
              </p>
              <HeroProgress done={done as number} total={total as number} label={`${name} 진행`} />
            </div>
          ))}
        </div>
        <p className="text-[12px] tracking-[-0.24px]">체크는 매장 단위로만 보여요</p>
      </HeroCard>
      <SectionTitle>확인해 주세요 · 2</SectionTitle>
      <CardLink href="/dev/kit?s=a5" title="디카페인 원두 어디 있어요?" meta="답하면 카드로 남아요" />
      <CardLink href="/dev/kit?s=a5" title="오트밀크 라떼도 시럽 2펌프인가요?" meta="답하면 카드로 남아요" />
      <Caption>질문이 오면 바로 알려드려요</Caption>
    </Screen>
  );
}

// ?s=gestures: 차례 등장·밀기·길게 누르기·이동해도 남는 토스트 (계획 2)
function GesturesPreview() {
  const { toast } = useFeedback();
  const router = useRouter();
  const [result, setResult] = useState("");
  const longPress = useLongPress(() => setResult("길게 눌렀어요"));
  return (
    <Screen>
      <PageHeader title="제스처" />
      <Stagger>
        <p>하나</p>
        <p>둘</p>
        <p>셋</p>
      </Stagger>
      <SwipeRow left={{ label: "빼기", tone: "danger", onAction: () => setResult("뺐어요") }}>
        <div className="rounded-[20px] bg-surface px-4 py-5 shadow-card">밀어 보세요</div>
      </SwipeRow>
      <Button variant="secondary" {...longPress}>
        꾹 눌러 보세요
      </Button>
      <Button
        variant="secondary"
        onClick={() => {
          toast("남아 있어요", { keepOnNavigate: true });
          router.push("/dev/kit?s=o6");
        }}
      >
        이동해도 남는 토스트
      </Button>
      {result && <p>{result}</p>}
    </Screen>
  );
}

// ?s=feedback: 토스트·스낵바·확인 창·배너 (G4)
function FeedbackPreview() {
  const { toast, snackbar } = useFeedback();
  const [confirm, setConfirm] = useState(false);
  const [result, setResult] = useState("");
  return (
    <Screen>
      <PageHeader title="피드백" />
      <Banner tone="danger" action={{ label: "다시 시도", onClick: () => setResult("다시 시도함") }}>
        처리하지 못한 자료가 있어요.
      </Banner>
      <Button onClick={() => toast("저장했어요")}>토스트 보기</Button>
      <Button variant="secondary" onClick={() => snackbar({ message: "지웠어요", actionLabel: "되돌리기", onAction: () => setResult("되돌렸어요") })}>
        스낵바 보기
      </Button>
      <Button variant="secondary" onClick={() => setConfirm(true)}>
        확인 창 보기
      </Button>
      {result && <p>{result}</p>}
      <ConfirmDialog
        open={confirm}
        title="로그아웃할까요?"
        confirmLabel="로그아웃"
        onCancel={() => setConfirm(false)}
        onConfirm={() => {
          setConfirm(false);
          setResult("확인함");
        }}
      />
    </Screen>
  );
}

export default function DevKitPage() {
  // 배포 빌드에서는 막는다. CI 화면 검사 빌드만 NEXT_PUBLIC_DEV_KIT=1 로 연다
  if (process.env.NODE_ENV === "production" && process.env.NEXT_PUBLIC_DEV_KIT !== "1") notFound();
  return (
    <div className="app-page">
      <div className="app-mobile-frame">
        <Suspense>
          <Preview />
        </Suspense>
      </div>
    </div>
  );
}
