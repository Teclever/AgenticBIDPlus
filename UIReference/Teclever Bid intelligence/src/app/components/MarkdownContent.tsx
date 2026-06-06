import ReactMarkdown from "react-markdown";

export function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none text-gray-800 prose-headings:text-gray-900 prose-headings:font-semibold prose-h2:text-lg prose-h2:mt-6 prose-h2:mb-2 prose-p:my-2 prose-ul:my-2 prose-li:my-0.5">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}
