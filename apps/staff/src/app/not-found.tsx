import Link from "next/link";
export default function NotFound() { return <div className="p-10"><h1 className="text-2xl font-semibold">This view isn’t available.</h1><Link href="/" className="mt-4 inline-block text-sm font-semibold text-brand-ink">Return to your review queue</Link></div>; }
