import { Suspense } from "react";
import RV2OwnerQuestions from "@/components/r-v2-owner-questions";
import { RLoading } from "@/components/r-v2-chat";

export default function Page() {
  return <Suspense fallback={<RLoading />}><RV2OwnerQuestions /></Suspense>;
}
