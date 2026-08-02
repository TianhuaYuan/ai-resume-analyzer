import { Rocket, Archive } from "@phosphor-icons/react";

export default function ProductUpdatesPage() {
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* 标题区 */}
        <div className="mb-6">
          <div className="flex items-center gap-2">
            <Rocket
              size={24}
              weight="duotone"
              className="text-brand"
              aria-hidden="true"
            />
            <h1 className="text-2xl font-bold text-[var(--color-text)]">产品更新</h1>
          </div>
          <p className="text-sm text-[var(--color-text-muted)] mt-1">
            了解最新功能与改进
          </p>
        </div>

        {/* 占位提示 */}
        <div className="flex flex-col items-center justify-center py-24">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl
            bg-[var(--color-bg-secondary)] border border-[var(--color-border)]
            text-[var(--color-text-muted)] mb-4">
            <Archive size={26} weight="duotone" aria-hidden="true" />
          </div>
          <h2 className="text-base font-semibold text-[var(--color-text)] mb-1.5">
            暂无更新
          </h2>
          <p className="text-sm text-[var(--color-text-muted)] text-center max-w-sm">
            还没有新的产品更新。我们会在发布新功能或改进后在这里同步给你。
          </p>
        </div>
      </div>
    </div>
  );
}
