import { redirect } from "next/navigation";

export default async function CardReviewDestination(
  props: PageProps<"/owner/cards/review">
) {
  const query = await props.searchParams;
  const rawJobId = Array.isArray(query.job_id) ? query.job_id[0] : query.job_id;
  const jobId = rawJobId && /^\d+$/.test(rawJobId) ? rawJobId : null;
  redirect(`/owner/cards?status=all${jobId ? `&job_id=${jobId}` : ""}`);
}
