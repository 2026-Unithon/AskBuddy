// 카카오톡 카드 메시지로 초대 링크를 보낸다. 로그인에는 쓰지 않는다(로그인은 서버 흐름).
// JavaScript 키는 공개 전제의 키다. 카카오 콘솔에 등록한 도메인에서만 동작한다.
const SDK_URL = "https://t1.kakaocdn.net/kakao_js_sdk/2.8.3/kakao.min.js";
const SDK_INTEGRITY = "sha384-oroumrnFVE0xtgqyDZJARgERibXg2C28380uaUZz2kHDS5CR7tu20eGiOU6GkTpy";
const JS_KEY = process.env.NEXT_PUBLIC_KAKAO_JS_KEY ?? "";

type KakaoSdk = {
  isInitialized(): boolean;
  init(key: string): void;
  Share: { sendDefault(options: Record<string, unknown>): void };
};
declare global { interface Window { Kakao?: KakaoSdk } }

let loading: Promise<KakaoSdk | null> | null = null;

function loadSdk(): Promise<KakaoSdk | null> {
  if (!JS_KEY || typeof window === "undefined") return Promise.resolve(null);
  if (window.Kakao) return Promise.resolve(window.Kakao);
  loading ??= new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = SDK_URL;
    script.integrity = SDK_INTEGRITY;
    script.crossOrigin = "anonymous";
    const timer = setTimeout(() => { loading = null; script.remove(); resolve(null); }, 5000);
    script.onload = () => { clearTimeout(timer); resolve(window.Kakao ?? null); };
    // 차단·오프라인이면 Web Share 로 넘어간다
    script.onerror = () => { clearTimeout(timer); script.remove(); loading = null; resolve(null); };
    document.head.appendChild(script);
  });
  return loading;
}

export async function shareInviteViaKakao(p: { url: string; storeName: string }): Promise<boolean> {
  const kakao = await loadSdk();
  if (!kakao) return false;
  try {
    if (!kakao.isInitialized()) kakao.init(JS_KEY);
    const link = { mobileWebUrl: p.url, webUrl: p.url };
    kakao.Share.sendDefault({
      objectType: "feed",
      content: {
        title: `${p.storeName}에서 초대했어요`,
        description: "AskBuddy로 매장 업무를 배워요. 눌러서 합류하세요.",
        imageUrl: new URL("/images/buddy-hero.png", window.location.origin).href,
        link,
      },
      buttons: [{ title: "합류하기", link }],
    });
    return true;
  } catch {
    return false;
  }
}
