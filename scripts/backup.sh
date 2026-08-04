#!/usr/bin/env bash
# ============================================================
# C6: 全量备份脚本（MySQL + ChromaDB + uploads 文件）
#
# 用法：
#   BACKUP_DIR=/var/backups/ai-resume ./scripts/backup.sh
#   crontab 示例（每天 3:17 备份，避开整点）：
#     17 3 * * * cd /opt/ai-resume-analyzer && BACKUP_DIR=/var/backups/ai-resume ./scripts/backup.sh >> /var/log/ai-resume-backup.log 2>&1
#
# 产物：$BACKUP_DIR/backup-<时间戳>.tar.gz（含 db.sql + chroma_data/ + uploads/）
# 保留最近 KEEP_N 份，自动清理旧备份。
# ============================================================
set -euo pipefail

# ── 配置（环境变量可覆盖）──────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-/var/backups/ai-resume}"
KEEP_N="${KEEP_N:-14}"                       # 保留份数
DB_NAME="${DB_NAME:-ai_resume}"
DB_USER="${DB_USER:-root}"
DB_PASS="${DB_PASS:-}"                       # 建议用 ~/.my.cnf 代替明文
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# ── 目录准备 ───────────────────────────────────────────
mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[$(date '+%F %T')] 开始备份 → $BACKUP_DIR/backup-$STAMP.tar.gz"

# ── 1. MySQL 全量 dump ─────────────────────────────────
if command -v mysqldump >/dev/null 2>&1; then
  MYSQL_ARGS=("--single-transaction" "--routines" "--triggers" "--default-character-set=utf8mb4")
  if [ -n "$DB_PASS" ]; then
    MYSQL_ARGS+=("-p$DB_PASS")
  fi
  mysqldump -u "$DB_USER" "${MYSQL_ARGS[@]}" "$DB_NAME" > "$TMP_DIR/db.sql"
  echo "  MySQL dump 完成: $(du -h "$TMP_DIR/db.sql" | cut -f1)"
else
  echo "  ! mysqldump 不存在，跳过 DB 备份"
fi

# ── 2. ChromaDB 向量库 + 上传文件 ──────────────────────
for src in chroma_data uploads; do
  if [ -d "$PROJECT_DIR/$src" ]; then
    cp -r "$PROJECT_DIR/$src" "$TMP_DIR/"
    echo "  已复制 $src/"
  fi
done

# ── 3. 打包 + 清理旧备份 ───────────────────────────────
tar -czf "$BACKUP_DIR/backup-$STAMP.tar.gz" -C "$TMP_DIR" .
echo "  打包完成: $(du -h "$BACKUP_DIR/backup-$STAMP.tar.gz" | cut -f1)"

# 保留最近 KEEP_N 份
ls -1t "$BACKUP_DIR"/backup-*.tar.gz 2>/dev/null | tail -n +$((KEEP_N + 1)) | while read -r old; do
  rm -f "$old"
  echo "  清理旧备份: $(basename "$old")"
done

echo "[$(date '+%F %T')] 备份完成 ✓"
