import { Suspense } from "react";
import RV2Chat, { RLoading } from "@/components/r-v2-chat";

export default function Page() {
  return <Suspense fallback={<RLoading />}><RV2Chat /></Suspense>;
}
