import { Suspense } from "react";
import { AskScreen } from "@/components/staff/ask-screen";

export default function StaffAskPage() {
  return (
    <Suspense>
      <AskScreen />
    </Suspense>
  );
}
