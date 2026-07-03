import { useEffect, useState, useRef } from "react";
import { Link } from "react-router-dom";
import {
  listResumes,
  uploadResume,
  deleteResume,
  type ResumeItem,
} from "../api/resumes";

export default function ResumeListPage() {
  const [resumes, setResumes] = useState<ResumeItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchResumes = async () => {
    setLoading(true);
    try {
      const data = await listResumes();
      setResumes(data.items);
      setTotal(data.total);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchResumes();
  }, []);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setError("");
    setUploading(true);
    try {
      await uploadResume(file);
      await fetchResumes();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
      // 重置 input，否则同一个文件再选不触发 onChange
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDelete = async (id: number, filename: string) => {
    if (!confirm(`确定删除「${filename}」吗？`)) return;
    try {
      await deleteResume(id);
      setResumes((prev) => prev.filter((r) => r.id !== id));
      setTotal((prev) => prev - 1);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-gray-900">
          我的简历{" "}
          <span className="text-sm font-normal text-gray-400">
            ({total} 份)
          </span>
        </h2>
        <div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx"
            onChange={handleUpload}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg
              hover:bg-blue-700 disabled:opacity-50 transition-colors cursor-pointer"
          >
            {uploading ? "上传中..." : "+ 上传简历"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-100 text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* 空状态 */}
      {!loading && resumes.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <p className="text-lg mb-2">还没有简历</p>
          <p className="text-sm">点击右上角「上传简历」开始</p>
        </div>
      )}

      {/* 列表 */}
      {resumes.length > 0 && (
        <div className="space-y-3">
          {resumes.map((r) => (
            <div
              key={r.id}
              className="flex items-center justify-between p-4 bg-white rounded-lg
                border border-gray-200 hover:border-blue-200 transition-colors"
            >
              <Link
                to={`/resumes/${r.id}`}
                className="flex-1 min-w-0 no-underline"
              >
                <p className="text-sm font-medium text-gray-900 truncate">
                  {r.filename}
                </p>
                <p className="text-xs text-gray-400 mt-1">
                  {r.chunk_count} 个分块 ·{" "}
                  {new Date(r.created_at).toLocaleDateString("zh-CN")}
                </p>
              </Link>
              <button
                onClick={() => handleDelete(r.id, r.filename)}
                className="ml-4 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50
                  rounded-md transition-colors cursor-pointer shrink-0"
              >
                删除
              </button>
            </div>
          ))}
        </div>
      )}

      {loading && (
        <div className="text-center py-8 text-gray-400 text-sm">加载中...</div>
      )}
    </div>
  );
}
