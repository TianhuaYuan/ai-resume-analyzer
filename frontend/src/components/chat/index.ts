/**
 * chat/ — QA 聊天域组件统一出口。
 *
 * 组件库分层（P0/P2）：对话外壳与交互（顶栏/列表/气泡/输入/欢迎/来源/滚动/SSE 编排）
 * 收敛于此域目录；渲染原语 + 生成式卡片（MarkdownRenderer/ScoreCard/JDMatchReport 等）
 * 与简历编辑器组件保持 components/ 顶层。
 */
export { default as ChatInput } from "./ChatInput";
export { default as MessageBubble } from "./MessageBubble";
export { default as WelcomeState } from "./WelcomeState";
export { default as AgentProcessPanel, getToolLabel } from "./AgentProcessPanel";
export {
  default as DiagnosisCard,
  isDiagnosisMessage,
  type DiagnosisSource,
} from "./DiagnosisCard";
export {
  type ChatMessage,
  normalizeHistorySources,
  formatTimestamp,
} from "./ChatMessage";
export { GUIDE_CARDS, type GuideCard } from "./GuideCards";
export {
  useAgentStream,
  type ApprovalRequest,
  type AgentStreamDeps,
  type SendQuestion,
  type SendQuestionOptions,
} from "./useAgentStream";
export { useChatScroll } from "./useChatScroll";
