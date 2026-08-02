import LandingNav from "../components/LandingNav";
import ContentSection from "../components/ContentSection";

/** 简历模板页 */
export default function TemplatesPage() {
  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <LandingNav activeKey="templates" />
      <ContentSection activeTab="templates" />
    </div>
  );
}
