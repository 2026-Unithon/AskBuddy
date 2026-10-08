"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Buddy, Button, Input, Shell } from "@/components/ui";
import { KakaoLoginButton } from "@/components/kakao-login-button";
import { AUTH_ERROR_COPY, ApiError, apiErrorMessage, login, refreshSession, requestJoin, signup } from "@/lib/api";
import { invitePreviewQuery, joinStatusQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

type EmailMode = "login" | "signup";

export function JoinClient({ inviteToken }: { inviteToken: string }) {
  const router = useRouter();
  const { state, dispatch, retrySession } = useApp();
  const queryClient = useQueryClient();
  const preview = useQuery(invitePreviewQuery(inviteToken));
  // 역할을 아직 안 고른 계정도 링크로 왔으면 알바로 요청한다(서버가 STAFF 로 정한다)
  const loggedInStaff = state.hydrated && state.token !== null && state.role !== "OWNER";
  const loggedInOwner = state.hydrated && state.token !== null && state.role === "OWNER";

  // 로그인돼 있으면 화면에 들어오자마자 합류 요청을 보낸다. 한 번만 보낸다(같은 키의 mutation)
  const join = useMutation({
    mutationKey: ["join-request", inviteToken],
    mutationFn: (accessToken: string) => requestJoin(inviteToken, accessToken),
    onSuccess: async (res) => {
      // 역할 미정이었다면 서버가 STAFF 로 정했다. 역할이 든 토큰을 다시 받는다
      const s = await refreshSession();
      dispatch({ type: "SET_AUTH", token: s.token, role: s.user.role, userId: s.user.user_id, storeId: s.user.store_id ?? null });
      await queryClient.invalidateQueries({ queryKey: joinStatusQuery(s.token, s.user.user_id).queryKey });
      router.replace(res.status === "ALREADY_MEMBER" ? "/staff/roadmap" : "/staff/pending");
    },
  });
  const { mutate, status: joinStatus } = join;
  useEffect(() => {
    if (loggedInStaff && preview.data && joinStatus === "idle") mutate(state.token!);
  }, [loggedInStaff, preview.data, joinStatus, mutate, state.token]);

  const [emailMode, setEmailMode] = useState<EmailMode | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const emailAuth = useMutation({
    mutationFn: () => emailMode === "login" ? login(email, password) : signup({ name, email, password }),
    onSuccess: ({ token: access, user }) => {
      queryClient.clear();
      dispatch({ type: "SET_AUTH", token: access, role: user.role, userId: user.user_id, storeId: user.store_id ?? null });
    },
  });
  const busy = emailAuth.isPending;
  const error = emailAuth.error instanceof ApiError && emailAuth.error.status === 401
    ? "이메일 또는 비밀번호가 맞지 않습니다"
    : emailAuth.error instanceof ApiError && emailAuth.error.status === 409
      ? "이미 가입된 이메일입니다. 로그인해 주세요"
      : emailAuth.error ? apiErrorMessage(emailAuth.error, "요청하지 못했어요.") : null;
  function submitEmail(e: FormEvent) {
    e.preventDefault();
    if (!busy && emailMode) emailAuth.mutate();
  }

  const invalid = preview.error instanceof ApiError && preview.error.status === 404;
  const joinErrorCode = join.error instanceof ApiError ? join.error.code : null;
  return (
    <Shell>
      <div className="flex flex-1 flex-col justify-center gap-5 px-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <Buddy size={96} />
          {(preview.isPending || !state.hydrated) && <p role="status" className="text-sm text-muted">초대 링크를 확인하고 있어요…</p>}
          {invalid && <p role="alert" className="text-sm font-medium">{AUTH_ERROR_COPY.INVITE_INVALID}</p>}
          {preview.isError && !invalid && (
            <>
              <p role="alert" className="text-sm text-danger-500">{apiErrorMessage(preview.error, "초대 링크를 확인하지 못했어요.")}</p>
              <Button onClick={() => void preview.refetch()}>다시 시도</Button>
            </>
          )}
          {preview.data && <h1 className="text-xl font-bold">{preview.data.store_name}에 합류합니다</h1>}
        </div>

        {preview.data && loggedInOwner && (
          <p role="alert" className="text-center text-sm">{AUTH_ERROR_COPY.ROLE_CONFLICT}</p>
        )}

        {preview.data && loggedInStaff && (
          <div className="text-center">
            {join.isPending && <p role="status" className="text-sm text-muted">합류 요청을 보내는 중…</p>}
            {join.isError && (
              <>
                <p role="alert" className="text-sm text-danger-500">
                  {joinErrorCode && AUTH_ERROR_COPY[joinErrorCode] ? AUTH_ERROR_COPY[joinErrorCode] : apiErrorMessage(join.error, "합류 요청을 보내지 못했어요.")}
                </p>
                <Button onClick={() => join.mutate(state.token!)}>다시 시도</Button>
              </>
            )}
          </div>
        )}

        {state.sessionError && <div role="alert"><p>로그인 상태를 확인하지 못했어요.</p><Button onClick={retrySession}>다시 시도</Button></div>}
        {preview.data && state.hydrated && !state.sessionError && !state.token && (
          <div className="space-y-3">
            <p className="text-center text-sm text-muted">가입하면 사장님이 승인한 뒤 시작할 수 있어요.</p>
            <KakaoLoginButton intent="STAFF_JOIN" invite={inviteToken} label="카카오로 시작하기" />
            <div className="flex justify-center gap-4 text-sm font-bold text-muted">
              <button type="button" className="underline" onClick={() => setEmailMode("login")}>이메일로 로그인</button>
              <button type="button" className="underline" onClick={() => setEmailMode("signup")}>이메일로 가입</button>
            </div>
            {emailMode && (
              <form onSubmit={submitEmail} className="space-y-2">
                {emailMode === "signup" && <Input aria-label="이름" value={name} onChange={(e) => setName(e.target.value)} placeholder="이름" required maxLength={50} />}
                <Input aria-label="이메일" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="이메일" required />
                <Input aria-label="비밀번호" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="비밀번호 6자 이상" required minLength={6} />
                {error && <p role="alert" className="text-xs text-danger-500">{error}</p>}
                <Button type="submit" className="w-full" loading={busy} loadingLabel="처리 중">
                  {emailMode === "login" ? "로그인하고 합류 요청" : "가입하고 합류 요청"}
                </Button>
              </form>
            )}
          </div>
        )}
      </div>
    </Shell>
  );
}
