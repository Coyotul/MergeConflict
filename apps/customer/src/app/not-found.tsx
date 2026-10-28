import Link from "next/link";
export default function NotFound() { return <div className="p-10"><h1 className="text-2xl font-semibold">This page isn’t in your workspace.</h1><Link href="/" className="mt-4 inline-block text-sm font-semibold text-brand-ink">Back to the assistant</Link></div>; }
