/**
 * 构建后压缩脚本：为 dist 下的静态资源生成 .gz / .br 预压缩文件。
 *
 * - .gz 由 nginx `gzip_static on` 伺服（nginx 官方镜像内置支持，零依赖）
 * - .br 备好供未来启用 brotli 的 nginx 镜像使用（nginx:alpine 默认无 brotli 模块）
 * - 只压缩 >= 1024 字节的文件（与 nginx gzip_min_length 对齐）
 */
import { gzipSync, brotliCompressSync, constants as zlibConstants } from "node:zlib";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";

const distDir = join(fileURLToPath(new URL(".", import.meta.url)), "..", "dist");
const MIN_SIZE = 1024;
const COMPRESSIBLE = new Set([".js", ".css", ".html", ".svg", ".json", ".txt", ".woff", ".woff2"]);

let count = 0;

function walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full);
    } else if (entry.isFile() && COMPRESSIBLE.has(extname(entry.name).toLowerCase())) {
      const src = readFileSync(full);
      if (src.length < MIN_SIZE) continue;
      writeFileSync(full + ".gz", gzipSync(src, { level: 9 }));
      writeFileSync(
        full + ".br",
        brotliCompressSync(src, {
          params: { [zlibConstants.BROTLI_PARAM_QUALITY]: 11 },
        }),
      );
      count += 1;
    }
  }
}

if (process.env.NODE_ENV !== "test") {
  walk(distDir);
  console.log(`[compress] 已生成 ${count} 个文件的 .gz/.br 预压缩产物`);
}
