import { Link } from "react-router-dom";

/**
 * C2: 用户协议页（信任合规）。
 * 服务条款：账号责任、合理使用、免责声明、终止权利。
 */
export default function TermsPage() {
  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-3xl px-4 py-12">
        <Link to="/" className="text-sm text-blue-600 hover:underline">
          ← 返回首页
        </Link>
        <h1 className="mt-4 text-3xl font-bold">用户协议</h1>
        <p className="mt-2 text-sm text-slate-500">最后更新：2026-08-04</p>

        <div className="mt-8 space-y-8 text-slate-700 leading-relaxed">
          <section>
            <h2 className="text-xl font-semibold text-slate-900">一、服务说明</h2>
            <p className="mt-3">
              本服务提供简历上传解析、AI 分析与问答、求职信息浏览与跟踪等功能。
              使用本服务即表示你同意本协议全部条款。
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-slate-900">二、账号责任</h2>
            <ul className="mt-3 list-disc space-y-1 pl-5">
              <li>你需对账号下的所有操作负责，请妥善保管登录凭证</li>
              <li>提供真实、准确的信息；不得冒用他人身份注册</li>
              <li>发现账号异常时应及时告知我们</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-slate-900">三、合理使用</h2>
            <ul className="mt-3 list-disc space-y-1 pl-5">
              <li>不得上传违法、侵权或包含恶意代码的内容</li>
              <li>不得利用本服务进行批量抓取、攻击或干扰系统运行</li>
              <li>不得试图绕过访问控制或获取他人数据（越权访问将导致账号封禁）</li>
              <li>不得将 AI 生成内容用于任何违法违规用途</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-slate-900">四、AI 服务免责声明</h2>
            <p className="mt-3">
              AI 分析与回答由大模型生成，仅供求职参考，不构成专业意见。
              对于因依赖 AI 内容产生的后果，本服务不承担责任。
              简历投递前请自行核对内容的真实性。
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-slate-900">五、服务变更与终止</h2>
            <ul className="mt-3 list-disc space-y-1 pl-5">
              <li>我们可能随时调整或暂停部分功能，重大变更将提前通知</li>
              <li>违反本协议时，我们有权暂停或终止你的账号</li>
              <li>你可在账户设置中随时注销账号并删除全部数据</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-slate-900">六、协议更新</h2>
            <p className="mt-3">
              本协议更新后将在本页面发布。持续使用服务即视为接受更新后的条款。
              数据相关条款详见
              <Link to="/privacy" className="text-blue-600 hover:underline">隐私政策</Link>。
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
