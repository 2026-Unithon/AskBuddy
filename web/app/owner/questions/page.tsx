import { redirect } from "next/navigation";
import { QuestionsList } from "./questions-list";

export default async function QuestionsPage({ searchParams }: PageProps<"/owner/questions">) {
  const { question_id: value } = await searchParams;
  const id = Array.isArray(value) ? value[0] : value;
  if (id && /^\d+$/.test(id)) redirect(`/owner/questions/${id}`);
  return <QuestionsList />;
}
