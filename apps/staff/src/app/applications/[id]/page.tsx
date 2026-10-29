import { ReviewDetail } from "@/components/review-detail";
export default async function ApplicationPage({ params }: { params: Promise<{ id: string }> }) { const { id } = await params; return <ReviewDetail key={id} id={id} />; }
