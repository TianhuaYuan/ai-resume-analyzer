import type { LucideIcon } from "lucide-react";
import { Search, FilePlus, Briefcase, GraduationCap, Map as MapIcon } from "lucide-react";

/** 空状态功能卡片配置（参考 UP简历：1 大卡 + 4 小卡 不对称网格） */
export interface GuideCard {
  icon: LucideIcon;
  label: string;
  description: string;
  primary?: boolean;
  span?: boolean;
  /** 点击发送问题 */
  question?: string;
  /** 点击跳转路由 */
  navigate?: string;
}

export const GUIDE_CARDS: GuideCard[] = [
  {
    icon: Search,
    label: "简历诊断",
    description: "从招聘者的视角分析简历问题",
    question: "请全面诊断这份简历的优点和不足",
    primary: true,
    span: true,
  },
  {
    icon: FilePlus,
    label: "创建简历",
    description: "快速开始一份新的简历",
    question: "请帮我创建一份简历",
  },
  {
    icon: Briefcase,
    label: "校招推荐",
    description: "实时搜索全网校招/社招岗位",
    question: "请实时搜索最近的校招和社招岗位机会",
  },
  {
    icon: GraduationCap,
    label: "面试准备",
    description: "面试真题量身定制",
    question: "请根据这份简历模拟一场面试",
  },
  {
    icon: MapIcon,
    label: "职业规划",
    description: "行业大牛手把手指导",
    question: "请帮我分析我的职业发展方向",
  },
];
