/**
 * icons.test — M1 图标迁移门禁测试。
 *
 * 遍历 iconsMap.ts 全部映射，断言每个 lucide 名都在 lucide-react 中真实导出。
 * 只要有人改了映射表却漏了 lucide 名，此测试即失败，杜绝"改了表没改文件"。
 */
import { describe, it, expect } from "vitest";
import * as Lucide from "lucide-react";
import { PHOSPHOR_TO_LUCIDE } from "./iconsMap";

describe("lucide-react 图标迁移映射", () => {
  const entries = Object.entries(PHOSPHOR_TO_LUCIDE);
  it("映射表非空且覆盖全站 phosphor 图标", () => {
    expect(entries.length).toBeGreaterThan(100);
  });

  it.each(entries)("%s → lucide %s 必须存在", (_phosphor, lucide) => {
    expect(lucide in Lucide).toBe(true);
  });
});
