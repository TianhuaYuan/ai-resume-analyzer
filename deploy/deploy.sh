#!/usr/bin/env bash
# 部署脚本：拉取镜像 + 启动服务 + 健康检查 + 回滚
# 用法：./deploy.sh <image_tag> [--rollback] [--dry-run]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="${DEPLOY_DIR}/docker-compose.prod.yml"
ENV_FILE="${DEPLOY_DIR}/.env"
ROLLBACK_FILE="${DEPLOY_DIR}/.rollback-info"
LOG_FILE="${DEPLOY_DIR}/deploy.log"

# 默认值（可通过环境变量覆盖）
DOCKER_REGISTRY="${DOCKER_REGISTRY:-docker.io}"
DOCKER_REPO="${DOCKER_REPO:-ai-resume-analyzer}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'  # No Color

log() {
  local msg="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
  echo -e "${GREEN}${msg}${NC}"
  echo "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

warn() {
  local msg="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: $*"
  echo -e "${YELLOW}${msg}${NC}"
  echo "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

error() {
  local msg="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: $*"
  echo -e "${RED}${msg}${NC}"
  echo "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

preflight() {
  log "Running preflight checks..."

  if ! command -v docker &>/dev/null; then
    error "Docker is not installed"
    exit 1
  fi

  if ! docker compose version &>/dev/null; then
    error "Docker Compose v2 is not installed"
    exit 1
  fi

  if [ ! -f "$COMPOSE_FILE" ]; then
    error "docker-compose.prod.yml not found at $COMPOSE_FILE"
    exit 1
  fi

  if [ ! -f "$ENV_FILE" ]; then
    error ".env file not found at $ENV_FILE"
    error "Copy .env.prod.example to .env and fill in values"
    exit 1
  fi

  log "Preflight checks passed"
}

load_env() {
  log "Loading environment from $ENV_FILE"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

pull_images() {
  local tag="$1"
  log "Pulling images with tag: $tag"

  docker pull "${DOCKER_REGISTRY}/${DOCKER_REPO}-backend:${tag}" || {
    error "Failed to pull backend image"
    exit 1
  }

  docker pull "${DOCKER_REGISTRY}/${DOCKER_REPO}-frontend:${tag}" || {
    error "Failed to pull frontend image"
    exit 1
  }

  log "Images pulled successfully"
}

start_services() {
  local tag="$1"
  log "Starting services with tag: $tag"

  export DOCKER_REGISTRY DOCKER_REPO
  export IMAGE_TAG="$tag"

  cd "$DEPLOY_DIR"
  docker compose -f docker-compose.prod.yml up -d --remove-orphans

  log "Services started"
}

wait_healthy() {
  log "Waiting for backend to become healthy (timeout: ${HEALTH_TIMEOUT}s)..."

  local elapsed=0
  local health="unknown"

  while [ $elapsed -lt "$HEALTH_TIMEOUT" ]; do
    health=$(docker inspect --format='{{.State.Health.Status}}' resume-backend 2>/dev/null || echo "unknown")

    if [ "$health" = "healthy" ]; then
      log "Backend is healthy after ${elapsed}s"
      return 0
    fi

    sleep 5
    elapsed=$((elapsed + 5))
    echo -ne "\r  waiting... ${elapsed}s / ${HEALTH_TIMEOUT}s (status=${health})"
  done

  echo ""
  error "Backend failed health check after ${HEALTH_TIMEOUT}s"
  return 1
}

show_status() {
  log "Current container status:"
  docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "resume-|NAMES" || true
}

cleanup() {
  log "Cleaning up dangling images..."
  docker image prune -f --filter "dangling=true" 2>/dev/null || true
}

rollback() {
  local target_tag="$1"

  if [ -z "$target_tag" ]; then
    if [ -f "$ROLLBACK_FILE" ]; then
      target_tag=$(grep "^ROLLBACK_TAG=" "$ROLLBACK_FILE" | cut -d= -f2)
    fi
  fi

  if [ -z "$target_tag" ]; then
    error "No rollback tag specified and no .rollback-info found"
    exit 1
  fi

  warn "Rolling back to tag: $target_tag"
  pull_images "$target_tag"
  start_services "$target_tag"

  if wait_healthy; then
    log "Rollback to $target_tag completed successfully"
  else
    error "Rollback failed — manual intervention required"
    exit 1
  fi
}

usage() {
  cat << EOF
Usage: $(basename "$0") <image_tag> [options]

Arguments:
  image_tag          Docker image tag to deploy (required for deploy/rollback)

Options:
  --rollback [tag]   Rollback to specified tag (or read from .rollback-info)
  --dry-run          Print commands without executing
  --status           Show current container status
  --cleanup          Clean up dangling images
  --help             Show this help message

Examples:
  $(basename "$0") abc123def456           # Deploy specific tag
  $(basename "$0") --rollback             # Rollback to last known good
  $(basename "$0") --rollback abc123      # Rollback to specific tag
  $(basename "$0") --status               # Check container status
EOF
}

main() {
  local image_tag=""
  local action="deploy"
  local dry_run=false

  while [ $# -gt 0 ]; do
    case "$1" in
      --rollback)
        action="rollback"
        shift
        if [ $# -gt 0 ] && [[ ! "$1" =~ ^-- ]]; then
          image_tag="$1"
          shift
        fi
        ;;
      --dry-run)
        dry_run=true
        shift
        ;;
      --status)
        action="status"
        shift
        ;;
      --cleanup)
        action="cleanup"
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        image_tag="$1"
        shift
        ;;
    esac
  done

  case "$action" in
    status)
      show_status
      exit 0
      ;;
    cleanup)
      cleanup
      exit 0
      ;;
    deploy|rollback)
      if [ -z "$image_tag" ]; then
        error "image_tag is required for $action"
        usage
        exit 1
      fi
      ;;
  esac

  preflight
  load_env

  if [ "$dry_run" = true ]; then
    log "=== DRY RUN ==="
    log "Action: $action"
    log "Image tag: $image_tag"
    log "Compose file: $COMPOSE_FILE"
    log "Registry: ${DOCKER_REGISTRY}/${DOCKER_REPO}"
    log "Would pull: ${DOCKER_REGISTRY}/${DOCKER_REPO}-backend:${image_tag}"
    log "Would pull: ${DOCKER_REGISTRY}/${DOCKER_REPO}-frontend:${image_tag}"
    log "Would run: docker compose -f $COMPOSE_FILE up -d"
    exit 0
  fi

  if [ "$action" = "rollback" ]; then
    rollback "$image_tag"
  else
    pull_images "$image_tag"
    start_services "$image_tag"

    if wait_healthy; then
      local old_backend
      old_backend=$(docker inspect --format='{{.Config.Image}}' resume-backend 2>/dev/null || echo "none")
      local old_frontend
      old_frontend=$(docker inspect --format='{{.Config.Image}}' resume-frontend 2>/dev/null || echo "none")

      cat > "$ROLLBACK_FILE" << EOF
ROLLBACK_TAG=${image_tag}
OLD_BACKEND=${old_backend}
OLD_FRONTEND=${old_frontend}
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

      cleanup
      show_status
      log "=== Deployment successful: $image_tag ==="
    else
      error "Deployment failed — attempting rollback..."
      if [ -f "$ROLLBACK_FILE" ]; then
        local prev_tag
        prev_tag=$(grep "^ROLLBACK_TAG=" "$ROLLBACK_FILE" | cut -d= -f2)
        if [ -n "$prev_tag" ] && [ "$prev_tag" != "$image_tag" ]; then
          warn "Auto-rolling back to $prev_tag"
          rollback "$prev_tag"
        fi
      fi
      exit 1
    fi
  fi
}

main "$@"
