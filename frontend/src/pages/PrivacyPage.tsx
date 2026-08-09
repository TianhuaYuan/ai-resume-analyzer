import { useState } from "react";
import { Link } from "react-router-dom";
import { exportDataCsv, exportDataJson, exportDataMarkdown } from "../api/auth";

type ExportFormat = "json" | "csv" | "markdown";

const EXPORT_BUTTONS: { fmt: ExportFormat; label: string; desc: string }[] = [
  { fmt: "json", label: "JSON", desc: "全部数据" },
  { fmt: "csv", label: "CSV", desc: "Excel 可直开" },
  { fmt: "markdown", label: "Markdown", desc: "摘要" },
];

/**
 * C2: 隐私政策页（信任合规）。
 * 面向校招简历产品，覆盖《个人信息保护法》要求的数据收集/使用/存储/
 * 权利行使（导出/删除/更正），并提供透明的 AI 处理说明。
 */
export default function PrivacyPage() {
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [exportError, setExportError] = useState("");

  const handleExport = async (fmt: ExportFormat) => {
    setExporting(fmt);
    setExportError("");
    try {
      if (fmt === "json") await exportDataJson();
      else if (fmt === "csv") await exportDataCsv();
      else await exportDataMarkdown();
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "导出失败");
    } finally {
      setExporting(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-3xl px-4 py-12">
        <Link to="/" className="text-sm text-blue-600 hover:underline">
          ← 返回首页
        </Link>
        <h1 className="mt-4 text-3xl font-bold">隐私政策</h1>
        <p className="mt-2 text-sm text-slate-500">最后更新：2026-08-04</p>

        <div className="mt-8 space-y-8 text-slate-700 leading-relaxed">
          <section>
            <h2 className="text-xl font-semibold text-slate-900">一、我们收集哪些信息</h2>
            <ul className="mt-3 list-disc space-y-1 pl-5">
              <li><strong>账户信息</strong>：注册时提供的邮箱、用户名、加密密码哈希</li>
              <li><strong>简历内容</strong>：你上传的简历文件（PDF/DOCX/TXT）及解析出的文本、结构化模块</li>
              <li><strong>使用记录</strong>：问答历史、求职跟踪记录、知识资产、意见反馈</li>
              <li><strong>技术日志</strong>：IP 地址、请求时间、错误日志（用于安全与排障）</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-slate-900">二、我们如何使用这些信息</h2>
            <ul className="mt-3 list-disc space-y-1 pl-5">
              <li>提供简历分析、问答、求职跟踪等核心功能</li>
              <li>AI 处理：你的简历内容会发送给第三方大模型服务商（DeepSeek 等）用于生成分析与回答</li>
              <li>改善产品：聚合统计使用情况（不包含可识别个人身份的内容）</li>
              <li>安全防护：检测滥用与恶意行为（如提示注入攻击）</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-slate-900">三、信息存储与保护</h2>
            <ul className="mt-3 list-disc space-y-1 pl-5">
              <li>数据存储在国内云服务器，采用加密传输（HTTPS）</li>
              <li>密码仅存哈希值，无法逆向还原</li>
              <li>向量数据库仅存简历文本分块，用于检索，不与其他服务共享</li>
              <li>访问控制：所有个人数据按账号隔离，仅本人可访问</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-slate-900">四、你的权利</h2>
            <ul className="mt-3 list-disc space-y-1 pl-5">
              <li><strong>查看与更正</strong>：登录后可在个人中心查看、编辑简历与历史</li>
              <li><strong>导出</strong>：可在账户设置导出你的全部数据（JSON / CSV / Markdown）</li>
              <li><strong>删除</strong>：可在账户设置注销账号，我们将在合理期限内清除全部数据</li>
              <li>行使权利无需额外费用</li>
            </ul>

            {/* 导出数据按钮组（E4：export-data 三种格式，需登录后使用） */}
            <div className="mt-5 rounded-list border border-slate-200 bg-white/70 p-5">
              <p className="text-sm font-semibold text-slate-800">导出你的全部数据</p>
              <p className="mt-1 text-xs text-slate-500">
                以三种格式下载当前账号下的全部简历数据（需登录后使用）
              </p>
              <div className="mt-3.5 flex flex-wrap gap-2.5">
                {EXPORT_BUTTONS.map((b) => (
                  <button
                    key={b.fmt}
                    onClick={() => void handleExport(b.fmt)}
                    disabled={exporting !== null}
                    className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-action
                      text-sm font-medium text-blue-600 bg-blue-50 border border-blue-200
                      hover:bg-blue-100 active:scale-[0.98] motion-reduce:active:scale-100
                      transition-all cursor-pointer
                      disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {exporting === b.fmt && (
                      <span
                        className="inline-block w-3 h-3 rounded-full border-2
                          border-blue-600 border-t-transparent animate-spin"
                        aria-hidden="true"
                      />
                    )}
                    {b.label}
                    <span className="text-[11px] text-blue-500 font-normal">({b.desc})</span>
                  </button>
                ))}
              </div>
              {exportError && (
                <p className="mt-3 text-xs text-danger" role="alert">
                  导出失败：{exportError}
                </p>
              )}
            </div>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-slate-900">五、AI 生成内容的说明</h2>
            <p className="mt-3">
              本产品的分析与回答由 AI 模型生成，可能存在误差或遗漏，请以简历原文为准。
              我们通过可溯源引用、拒答阈值等方式降低幻觉风险，但 AI 内容不构成任何承诺。
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-slate-900">六、联系方式与政策更新</h2>
            <p className="mt-3">
              政策变更将在本页面发布并更新日期。如有疑问可通过
              <Link to="/feedback" className="text-blue-600 hover:underline">意见箱</Link>
              联系我们。
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
