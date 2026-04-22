#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE_DEFAULT="docker.cnb.cool/btpanel/openclaw:latest"
BASE_DIR_DEFAULT="/data/openclaw"
TZ_DEFAULT="Asia/Shanghai"
ROOT_DOMAIN_DEFAULT="huxs.cn"
REPO_URL_DEFAULT="https://github.com/openclaw/openclaw.git"
REPO_BRANCH_DEFAULT="main"
USE_GIT_SOURCE=0

# openclaw-lark 插件配置
LARK_PLUGIN_REPO="https://github.com/landingdang/openclaw-lark.git"
LARK_PLUGIN_BRANCH="main"
INSTALL_LARK_PLUGIN=0

CREATED_DIR=0
TARGET_DIR=""

green()  { echo -e "\033[1;32m$*\033[0m"; }
yellow() { echo -e "\033[1;33m$*\033[0m"; }
red()    { echo -e "\033[1;31m$*\033[0m" >&2; }

on_error() {
  local exit_code=$?
  red "脚本执行失败，退出码：${exit_code}"
  yellow "已存在的其他实例没有被修改。"
  if [[ "$CREATED_DIR" -eq 1 && -n "${TARGET_DIR:-}" ]]; then
    yellow "当前新实例目录已保留，便于你排查：${TARGET_DIR}"
  fi
  exit "$exit_code"
}
trap on_error ERR

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    red "缺少命令：$1"
    exit 1
  }
}

need_cmd_any() {
  local found=0
  for cmd in "$@"; do
    if command -v "$cmd" >/dev/null 2>&1; then
      found=1
      break
    fi
  done
  if [[ $found -eq 0 ]]; then
    red "缺少以下任一命令：$*"
    exit 1
  fi
}

trim() {
  local s="$*"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

ask_with_default() {
  local prompt="$1"
  local default_value="$2"
  local val
  read -r -p "${prompt} [默认: ${default_value}]: " val
  val="$(trim "$val")"
  [[ -z "$val" ]] && printf '%s' "$default_value" || printf '%s' "$val"
}

ask_required() {
  local prompt="$1"
  local val
  while true; do
    read -r -p "${prompt}: " val
    val="$(trim "$val")"
    [[ -n "$val" ]] && { printf '%s' "$val"; return; }
    yellow "不能为空，请重新输入。"
  done
}

ask_yes_no() {
  local prompt="$1"
  local default_value="${2:-n}"
  local val
  local hint="[y/N]"
  [[ "$default_value" == "y" ]] && hint="[Y/n]"

  while true; do
    read -r -p "${prompt} ${hint}: " val
    val="$(trim "$val")"
    [[ -z "$val" ]] && val="$default_value"
    case "${val,,}" in
      y|yes) return 0 ;;
      n|no)  return 1 ;;
      *) yellow "请输入 y/Y/yes 或 n/N/no" ;;
    esac
  done
}

is_number() {
  [[ "$1" =~ ^[0-9]+$ ]]
}

valid_name() {
  [[ "$1" =~ ^[a-zA-Z0-9_-]+$ ]]
}

valid_subdomain_label() {
  [[ "$1" =~ ^[a-z0-9-]+$ ]]
}

realpath_safe() {
  python3 - <<'PY' "$1"
import os,sys
print(os.path.realpath(sys.argv[1]))
PY
}

read_metadata_value() {
  local file="$1"
  local key="$2"
  [[ -f "$file" ]] || return 1
  awk -F'=' -v key="$key" '$1 == key {print substr($0, index($0, "=") + 1)}' "$file" | tail -n 1
}

set_metadata_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  touch "$file"
  if grep -q "^${key}=" "$file"; then
    python3 - "$file" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()
updated = []
replaced = False
for line in lines:
    if line.startswith(f"{key}="):
        updated.append(f"{key}={value}")
        replaced = True
    else:
        updated.append(line)
if not replaced:
    updated.append(f"{key}={value}")
path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
  else
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}

ensure_git_source() {
  local source_dir="$1"
  local repo_url="$2"
  local branch="$3"

  mkdir -p "$(dirname "$source_dir")"
  if [[ -d "$source_dir/.git" ]]; then
    green "更新共享源码仓库"
    git -C "$source_dir" fetch --tags origin
    git -C "$source_dir" checkout "$branch"
    git -C "$source_dir" pull --ff-only origin "$branch"
  elif [[ -e "$source_dir" ]]; then
    red "源码目录已存在但不是 Git 仓库：$source_dir"
    exit 1
  else
    green "克隆共享源码仓库"
    git clone --branch "$branch" --single-branch "$repo_url" "$source_dir"
  fi
}

build_image_from_source() {
  local source_dir="$1"
  local image_tag="$2"

  green "从源码构建 Docker 镜像"
  (
    cd "$source_dir"
    docker build -t "$image_tag" .
  )
}

# ============================================================
# openclaw-lark 插件相关函数
# ============================================================

ensure_lark_plugin() {
  local plugin_dir="$1"
  local repo_url="$2"
  local branch="$3"

  if [[ -d "$plugin_dir/.git" ]]; then
    green "更新 openclaw-lark 插件源码"
    (
      cd "$plugin_dir"
      if ! git fetch origin 2>/dev/null; then
        yellow "网络连接失败，跳过更新，使用现有源码"
        return 0
      fi
      git checkout "$branch"
      git pull origin "$branch" || {
        yellow "更新失败，使用现有源码"
        return 0
      }
    )
  elif [[ -d "$plugin_dir" && -f "$plugin_dir/package.json" ]]; then
    green "检测到已存在的插件源码目录（非 Git 仓库）"
    yellow "跳过克隆，使用现有源码：$plugin_dir"
  else
    green "克隆 openclaw-lark 插件源码"
    mkdir -p "$(dirname "$plugin_dir")"
    if ! git clone --branch "$branch" --single-branch "$repo_url" "$plugin_dir" 2>/dev/null; then
      red "克隆插件源码失败"
      yellow "可能的原因："
      echo "  1. 网络连接问题"
      echo "  2. GitHub 访问受限"
      echo
      yellow "解决方案："
      echo "  1. 检查网络连接后重试"
      echo "  2. 手动下载插件源码到：$plugin_dir"
      echo "  3. 跳过插件安装，后续手动安装"
      return 1
    fi
  fi
}

build_lark_plugin() {
  local plugin_dir="$1"
  local output_dir="$2"

  green "构建 openclaw-lark 插件"

  # 检查 pnpm 是否安装
  if ! command -v pnpm &>/dev/null; then
    yellow "pnpm 未安装，正在安装..."
    # 使用 npm 官方源安装 pnpm，避免镜像源问题
    npm install -g pnpm --registry=https://registry.npmjs.org/
  fi

  (
    cd "$plugin_dir"

    # 安装依赖
    green "安装插件依赖"
    pnpm install

    # 构建
    green "构建插件"
    pnpm run build

    # 打包
    green "打包插件"
    pnpm pack

    # 移动到输出目录（处理 scope 包名）
    mkdir -p "$output_dir"
    # pnpm pack 生成的文件名格式：larksuite-openclaw-lark-2026.4.1.tgz
    mv larksuite-openclaw-lark-*.tgz "$output_dir/openclaw-lark.tgz" 2>/dev/null || \
      mv openclaw-lark-*.tgz "$output_dir/openclaw-lark.tgz"

    green "插件包已生成: $output_dir/openclaw-lark.tgz"
  )
}

install_lark_plugin_to_instance() {
  local instance_dir="$1"
  local plugin_package="$2"

  green "安装 openclaw-lark 插件到实例"

  # 创建 extensions 目录（不要重复 .openclaw）
  mkdir -p "$instance_dir/config/extensions"

  # 将插件包复制到 extensions 目录
  cp "$plugin_package" "$instance_dir/config/extensions/"

  # 在容器中安装插件
  (
    cd "$instance_dir"
    docker compose run --rm --no-deps openclaw-gateway \
      plugins install /home/node/.openclaw/extensions/openclaw-lark.tgz
  )

  # 启用插件
  (
    cd "$instance_dir"
    docker compose run --rm --no-deps openclaw-gateway \
      plugins enable openclaw-lark
  )

  green "插件安装并启用完成"
}

collect_reserved_ports() {
  local base_dir="$1"
  local exclude_dir="${2:-}"
  local ports=()

  # 1. 从其他实例的 instance.env 收集端口
  if [[ -d "$base_dir" ]]; then
    while IFS= read -r -d '' env_file; do
      local instance_dir
      instance_dir="$(dirname "$env_file")"
      [[ -n "$exclude_dir" && "$instance_dir" == "$exclude_dir" ]] && continue

      local gw_port bridge_port
      gw_port="$(read_metadata_value "$env_file" GATEWAY_PORT 2>/dev/null || true)"
      bridge_port="$(read_metadata_value "$env_file" BRIDGE_PORT 2>/dev/null || true)"
      [[ -n "$gw_port" ]] && ports+=("$gw_port")
      [[ -n "$bridge_port" ]] && ports+=("$bridge_port")
    done < <(find "$base_dir" -mindepth 2 -maxdepth 2 -type f -name "instance.env" -print0 2>/dev/null)
  fi

  # 2. 从 compose.yaml 文件收集端口
  if [[ -d "$base_dir" ]]; then
    while IFS= read -r -d '' compose_file; do
      local instance_dir
      instance_dir="$(dirname "$compose_file")"
      [[ -n "$exclude_dir" && "$instance_dir" == "$exclude_dir" ]] && continue

      local ui_port bridge_port
      ui_port="$(extract_ui_port "$compose_file" 2>/dev/null || true)"
      bridge_port="$(extract_bridge_port "$compose_file" 2>/dev/null || true)"
      [[ -n "$ui_port" ]] && ports+=("$ui_port")
      [[ -n "$bridge_port" ]] && ports+=("$bridge_port")
    done < <(find "$base_dir" -mindepth 2 -maxdepth 2 -type f -name "compose.yaml" -print0 2>/dev/null)
  fi

  # 3. 从系统监听端口收集
  if command -v netstat &>/dev/null; then
    while IFS= read -r line; do
      local port
      port="$(echo "$line" | awk '{print $4}' | rev | cut -d: -f1 | rev)"
      [[ "$port" =~ ^[0-9]+$ ]] && ports+=("$port")
    done < <(netstat -tuln 2>/dev/null | grep LISTEN || true)
  fi

  # 去重并输出
  printf '%s\n' "${ports[@]}" 2>/dev/null | sort -un | tr '\n' ' '
}

is_port_available() {
  local port="$1"
  local reserved="$2"

  # 检查是否在保留列表中
  if [[ " $reserved " == *" $port "* ]]; then
    return 1
  fi

  # 检查端口是否被监听
  if command -v netstat &>/dev/null; then
    if netstat -tuln 2>/dev/null | grep -q ":$port "; then
      return 1
    fi
  fi

  return 0
}

pick_available_port() {
  local start_port="${1:-28089}"
  local reserved="$2"
  local port="$start_port"

  while ! is_port_available "$port" "$reserved"; do
    ((port++))
    if [[ $port -gt 65535 ]]; then
      red "无法找到可用端口（从 $start_port 开始）"
      exit 1
    fi
  done

  echo "$port"
}

extract_ui_port() {
  local compose_file="$1"
  awk -F'"' '/127\.0\.0\.1:[0-9]+:18789/ {print $2}' "$compose_file" | awk -F: '{print $2}' | head -n1
}

extract_bridge_port() {
  local compose_file="$1"
  awk -F'"' '/127\.0\.0\.1:[0-9]+:18790/ {print $2}' "$compose_file" | awk -F: '{print $2}' | head -n1
}

extract_project_name() {
  local compose_file="$1"
  awk -F': ' '/^name:/ {print $2}' "$compose_file" | head -n1
}

extract_domain_hint() {
  local dir="$1"
  local f
  f="$(find "$dir" -maxdepth 1 -type f -name 'nginx-*.conf' | head -n1 || true)"
  if [[ -n "$f" ]]; then
    basename "$f" | sed 's/^nginx-//; s/\.conf$//'
  else
    printf '%s' '-'
  fi
}

list_existing_instances() {
  local base_dir="$1"
  local found=0
  local dirs=()

  shopt -s nullglob
  dirs=("$base_dir"/*)
  shopt -u nullglob

  for d in "${dirs[@]}"; do
    [[ -d "$d" ]] || continue
    [[ -f "$d/compose.yaml" ]] || continue
    found=1
  done

  if [[ "$found" -eq 0 ]]; then
    yellow "当前未发现已部署实例。"
    return 0
  fi

  printf "%-10s %-20s %-10s %-10s %-30s\n" "短名" "项目名" "UI端口" "桥接端口" "域名"
  printf "%-10s %-20s %-10s %-10s %-30s\n" "----" "------" "------" "--------" "----"

  for d in "${dirs[@]}"; do
    [[ -d "$d" ]] || continue
    [[ -f "$d/compose.yaml" ]] || continue
    local short_name project_name ui_port bridge_port domain_hint
    short_name="$(basename "$d")"
    project_name="$(extract_project_name "$d/compose.yaml")"
    ui_port="$(extract_ui_port "$d/compose.yaml")"
    bridge_port="$(extract_bridge_port "$d/compose.yaml")"
    domain_hint="$(extract_domain_hint "$d")"
    printf "%-10s %-20s %-10s %-10s %-30s\n" \
      "$short_name" "${project_name:--}" "${ui_port:--}" "${bridge_port:--}" "${domain_hint:--}"
  done
}

project_name_exists() {
  local base_dir="$1"
  local project_name="$2"
  local f
  shopt -s nullglob
  for f in "$base_dir"/*/compose.yaml; do
    grep -Eq "^name:[[:space:]]*${project_name}$" "$f" && return 0
  done
  shopt -u nullglob
  return 1
}

domain_exists() {
  local base_dir="$1"
  local domain="$2"
  local f

  shopt -s nullglob
  for f in "$base_dir"/*/nginx-"$domain".conf; do
    [[ -e "$f" ]] && return 0
  done
  for f in "$base_dir"/*/README-BT.txt; do
    grep -Fq "https://${domain}" "$f" && return 0
  done
  shopt -u nullglob

  return 1
}

port_listening() {
  local port="$1"
  ss -lnt 2>/dev/null | awk '{print $4}' | grep -E "(^|:)$port$" >/dev/null 2>&1
}

port_declared_file() {
  local base_dir="$1"
  local port="$2"
  local f

  shopt -s nullglob
  for f in "$base_dir"/*/compose.yaml; do
    if grep -Eq "127\.0\.0\.1:${port}:18789|127\.0\.0\.1:${port}:18790" "$f"; then
      echo "$f"
      shopt -u nullglob
      return 0
    fi
  done
  shopt -u nullglob
  return 1
}

build_allowed_origins_json() {
  local domain="$1"
  local ui_port="$2"
  printf '["https://%s","http://127.0.0.1:%s","http://localhost:%s"]' \
    "$domain" "$ui_port" "$ui_port"
}

write_compose_file() {
  local dir="$1"
  local project_name="$2"
  local image="$3"
  local timezone="$4"
  local ui_port="$5"
  local bridge_port="$6"

  local tmp_file="${dir}/compose.yaml.tmp.$$"

  cat > "${tmp_file}" <<EOF
name: ${project_name}

services:
  openclaw-gateway:
    image: ${image}
    pull_policy: missing
    environment:
      HOME: /home/node
      TERM: xterm-256color
      TZ: ${timezone}
    volumes:
      - ${dir}/config:/home/node/.openclaw
      - ${dir}/workspace:/home/node/.openclaw/workspace
    ports:
      - "127.0.0.1:${ui_port}:18789"
      - "127.0.0.1:${bridge_port}:18790"
    init: true
    restart: unless-stopped
    command: ["node", "dist/index.js", "gateway", "--bind", "lan", "--port", "18789"]
    healthcheck:
      test:
        [
          "CMD",
          "node",
          "-e",
          "fetch('http://127.0.0.1:18789/healthz').then((r)=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
        ]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 20s

  openclaw-cli:
    image: ${image}
    pull_policy: missing
    network_mode: "service:openclaw-gateway"
    environment:
      HOME: /home/node
      TERM: xterm-256color
      BROWSER: echo
      TZ: ${timezone}
    volumes:
      - ${dir}/config:/home/node/.openclaw
      - ${dir}/workspace:/home/node/.openclaw/workspace
    stdin_open: true
    tty: true
    init: true
    entrypoint: ["node", "dist/index.js"]
    depends_on:
      - openclaw-gateway
EOF

  mv "${tmp_file}" "${dir}/compose.yaml"
}

write_nginx_snippet() {
  local dir="$1"
  local domain="$2"
  local ui_port="$3"

  cat > "${dir}/nginx-${domain}.conf" <<EOF
# 宝塔站点 ${domain} 的 Nginx 配置片段
location / {
    proxy_pass http://127.0.0.1:${ui_port};
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600;
}
EOF
}

write_readme() {
  local dir="$1"
  local project_name="$2"
  local domain="$3"
  local ui_port="$4"
  local bridge_port="$5"

  cat > "${dir}/README-BT.txt" <<EOF
项目名: ${project_name}
目录: ${dir}
Compose文件: ${dir}/compose.yaml

正式访问:
  https://${domain}

本机调试:
  http://127.0.0.1:${ui_port}

桥接端口:
  127.0.0.1:${bridge_port} -> container:18790

Nginx片段:
  ${dir}/nginx-${domain}.conf

常用命令:
  cd ${dir}
  docker compose ps
  docker compose logs -f openclaw-gateway
  docker compose run --rm openclaw-cli dashboard --no-open
  docker compose run --rm openclaw-cli devices list
  docker compose run --rm openclaw-cli devices approve <requestId>
EOF
}

health_wait() {
  local port="$1"
  local ok=0
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${port}/healthz" >/dev/null 2>&1; then
      ok=1
      break
    fi
    sleep 2
  done

  if [[ "$ok" -eq 1 ]]; then
    green "健康检查通过：http://127.0.0.1:${port}/healthz"
  else
    yellow "健康检查暂未通过，建议执行日志检查。"
  fi
}

main() {
  need_cmd docker
  need_cmd curl
  need_cmd_any ss netstat
  need_cmd awk
  need_cmd grep
  need_cmd find
  need_cmd sed
  need_cmd python3

  if [[ "$(id -u)" -ne 0 ]]; then
    red "请用 root 运行。"
    exit 1
  fi

  if ! docker compose version >/dev/null 2>&1; then
    red "当前环境不可用 docker compose。"
    exit 1
  fi

  clear || true
  green "================================================"
  green " OpenClaw 多实例部署脚本（增强版）"
  green " - 支持新建实例和更新配置"
  green " - 智能端口分配和冲突检测"
  green " - Git 源码管理（可选）"
  green "================================================"
  echo

  local image base_dir timezone root_domain use_git git_repo git_branch
  image="$(ask_with_default "请输入镜像名" "$IMAGE_DEFAULT")"
  base_dir="$(ask_with_default "请输入基础部署目录" "$BASE_DIR_DEFAULT")"
  timezone="$(ask_with_default "请输入时区" "$TZ_DEFAULT")"
  root_domain="$(ask_with_default "请输入主域名" "$ROOT_DOMAIN_DEFAULT")"

  [[ "$base_dir" = /* ]] || { red "基础部署目录必须是绝对路径。"; exit 1; }
  [[ "$base_dir" != "/" ]] || { red "基础部署目录不能是 /"; exit 1; }

  # Git 源码管理选项
  echo
  green "源码管理选项："
  echo "  1) 使用 Docker 镜像内置源码（默认）"
  echo "  2) 使用 Git 仓库源码（共享源码，节省空间）"
  echo
  local git_choice
  git_choice="$(ask_with_default "请选择源码管理方式 [1/2]" "1")"

  if [[ "$git_choice" == "2" ]]; then
    use_git=1
    git_repo="$(ask_with_default "Git 仓库地址" "$REPO_URL_DEFAULT")"
    git_branch="$(ask_with_default "Git 分支" "$REPO_BRANCH_DEFAULT")"

    green "将使用 Git 源码管理："
    echo "  仓库: $git_repo"
    echo "  分支: $git_branch"
    echo "  源码将克隆到: ${base_dir}/shared-source"
    echo
  else
    use_git=0
    green "将使用 Docker 镜像内置源码"
    echo
  fi

  mkdir -p "$base_dir"
  local base_real
  base_real="$(realpath_safe "$base_dir")"

  echo
  green "当前已发现的实例："
  list_existing_instances "$base_dir"
  echo

  local short_name project_name target_dir target_real metadata_file
  local is_update=0 existing_ui_port existing_bridge_port existing_domain

  while true; do
    short_name="$(ask_required "实例短名（例如 a / b / c）")"
    if ! valid_name "$short_name"; then
      yellow "实例短名只允许字母、数字、下划线、中划线。"
      continue
    fi

    project_name="openclaw-${short_name}"
    target_dir="${base_dir}/${short_name}"
    target_real="${base_real}/${short_name}"
    metadata_file="${target_dir}/instance.env"

    # 检查是否是更新现有实例
    if [[ -e "$target_dir" ]]; then
      if [[ -f "$metadata_file" ]]; then
        is_update=1
        existing_ui_port="$(read_metadata_value "$metadata_file" GATEWAY_PORT 2>/dev/null || true)"
        existing_bridge_port="$(read_metadata_value "$metadata_file" BRIDGE_PORT 2>/dev/null || true)"
        existing_domain="$(read_metadata_value "$metadata_file" DOMAIN 2>/dev/null || true)"

        yellow "检测到现有实例：$target_dir"
        echo "  现有 UI 端口: ${existing_ui_port:--}"
        echo "  现有桥接端口: ${existing_bridge_port:--}"
        echo "  现有域名: ${existing_domain:--}"
        echo

        if ask_yes_no "是否更新此实例的配置" "y"; then
          break
        else
          continue
        fi
      else
        yellow "目录已存在但不是有效实例：$target_dir"
        continue
      fi
    fi

    if project_name_exists "$base_dir" "$project_name"; then
      yellow "项目名已存在：${project_name}"
      continue
    fi

    break
  done

  local prefix domain
  if [[ $is_update -eq 1 && -n "$existing_domain" ]]; then
    # 更新模式：使用现有域名作为默认值
    while true; do
      domain="$(ask_with_default "域名" "$existing_domain")"

      if [[ "$domain" != "$existing_domain" ]] && domain_exists "$base_dir" "$domain"; then
        yellow "域名已被其他实例使用：${domain}"
        continue
      fi

      # 如果域名变更，清理旧的 nginx 配置文件
      if [[ "$domain" != "$existing_domain" && -f "${target_dir}/nginx-${existing_domain}.conf" ]]; then
        yellow "域名已变更，将删除旧的 Nginx 配置文件"
        rm -f "${target_dir}/nginx-${existing_domain}.conf"
      fi

      break
    done
  else
    # 新建模式：使用主域名前缀
    while true; do
      prefix="$(ask_required "二级域名前缀（例如 oc3）")"
      if ! valid_subdomain_label "$prefix"; then
        yellow "二级域名前缀只允许小写字母、数字、中划线。"
        continue
      fi

      domain="${prefix}.${root_domain}"

      if domain_exists "$base_dir" "$domain"; then
        yellow "域名已被现有实例使用：${domain}"
        continue
      fi

      break
    done
  fi

  # 智能端口分配
  local reserved_ports
  reserved_ports="$(collect_reserved_ports "$base_dir" "$target_dir")"

  local ui_port_default bridge_port_default
  if [[ $is_update -eq 1 ]]; then
    # 更新模式：使用现有端口作为默认值
    ui_port_default="${existing_ui_port:-28089}"
    bridge_port_default="${existing_bridge_port:-29089}"
  else
    # 新建模式：智能分配端口
    ui_port_default="$(pick_available_port 28089 "$reserved_ports")"
    bridge_port_default="$(pick_available_port $((ui_port_default + 1)) "$reserved_ports $ui_port_default")"
  fi

  green "端口分配建议："
  echo "  UI 端口: ${ui_port_default}"
  echo "  桥接端口: ${bridge_port_default}"
  echo

  local ui_port
  while true; do
    ui_port="$(ask_with_default "UI 端口" "$ui_port_default")"
    if ! is_number "$ui_port" || (( ui_port < 1 || ui_port > 65535 )); then
      yellow "端口必须是 1-65535 的数字。"
      continue
    fi

    # 更新模式下，如果端口未变化则跳过检查
    if [[ $is_update -eq 1 && "$ui_port" == "$existing_ui_port" ]]; then
      break
    fi

    if port_listening "$ui_port"; then
      yellow "端口当前正在被监听：${ui_port}"
      continue
    fi

    local declared_file=""
    declared_file="$(port_declared_file "$base_dir" "$ui_port" || true)"
    if [[ -n "$declared_file" ]]; then
      yellow "端口已在其他实例 compose 中声明：${ui_port}"
      yellow "冲突文件：${declared_file}"
      continue
    fi

    break
  done

  local bridge_port
  while true; do
    bridge_port="$(ask_with_default "桥接端口" "$bridge_port_default")"
    if ! is_number "$bridge_port" || (( bridge_port < 1 || bridge_port > 65535 )); then
      yellow "端口必须是 1-65535 的数字。"
      continue
    fi

    if [[ "$bridge_port" == "$ui_port" ]]; then
      yellow "桥接端口不能和 UI 端口相同。"
      continue
    fi

    # 更新模式下，如果端口未变化则跳过检查
    if [[ $is_update -eq 1 && "$bridge_port" == "$existing_bridge_port" ]]; then
      break
    fi

    if port_listening "$bridge_port"; then
      yellow "端口当前正在被监听：${bridge_port}"
      continue
    fi

    local declared_file=""
    declared_file="$(port_declared_file "$base_dir" "$bridge_port" || true)"
    if [[ -n "$declared_file" ]]; then
      yellow "端口已在其他实例 compose 中声明：${bridge_port}"
      yellow "冲突文件：${declared_file}"
      continue
    fi

    break
  done

  # openclaw-lark 插件安装选项
  local install_lark=0
  if [[ $is_update -eq 0 ]]; then
    echo
    green "openclaw-lark 插件选项："
    echo "  openclaw-lark 是飞书集成插件，提供飞书机器人功能"
    echo "  仓库: $LARK_PLUGIN_REPO"
    echo
    if ask_yes_no "是否安装 openclaw-lark 插件" "n"; then
      install_lark=1
      green "将在部署完成后安装 openclaw-lark 插件"
    else
      green "跳过插件安装"
    fi
  fi

  echo
  if [[ $is_update -eq 1 ]]; then
    green "请确认本次更新配置："
    echo "操作模式   : 更新现有实例"
  else
    green "请确认本次只会新增这个实例："
    echo "操作模式   : 新建实例"
  fi
  echo "实例短名   : ${short_name}"
  echo "项目名     : ${project_name}"
  echo "实例目录   : ${target_dir}"
  echo "镜像       : ${image}"
  echo "时区       : ${timezone}"
  echo "域名       : ${domain}"
  echo "UI端口     : 127.0.0.1:${ui_port} -> 18789"
  echo "桥接端口   : 127.0.0.1:${bridge_port} -> 18790"
  echo

  if ! ask_yes_no "确认开始部署" "y"; then
    yellow "已取消。"
    exit 0
  fi

  local confirm_text
  if [[ $is_update -eq 1 ]]; then
    confirm_text="UPDATE ${short_name}"
  else
    confirm_text="ADD ${short_name}"
  fi
  local typed
  echo "最终确认：请输入 ${confirm_text}"
  read -r -p "> " typed
  typed="$(trim "$typed")"
  [[ "$typed" == "$confirm_text" ]] || { red "确认失败，已取消。"; exit 1; }

  # Git 源码管理
  if [[ $use_git -eq 1 ]]; then
    green "[1/10] 同步 Git 源码"
    local shared_source="${base_dir}/shared-source"
    ensure_git_source "$shared_source" "$git_repo" "$git_branch"

    green "[2/10] 从源码构建镜像"
    build_image_from_source "$shared_source" "$image"
  else
    green "[1/10] 跳过 Git 源码同步（使用镜像内置源码）"
    green "[2/10] 检查镜像"
    if ! docker image inspect "${image}" >/dev/null 2>&1; then
      yellow "本地未找到镜像：${image}"
      echo
      yellow "本地已有的 openclaw 相关镜像："
      docker images | grep -E "openclaw|btpanel" || echo "  未找到相关镜像"
      echo
      yellow "可能的原因："
      echo "  1. 镜像名称或标签不匹配"
      echo "  2. 宝塔面板下载的镜像名称不同"
      echo
      if ask_yes_no "是否尝试从远程拉取镜像" "y"; then
        if ! docker pull "${image}"; then
          red "镜像拉取失败"
          yellow "请手动检查并修正镜像名称，或使用以下命令标记现有镜像："
          echo "  docker tag <现有镜像名> ${image}"
          exit 1
        fi
        green "镜像拉取成功"
      else
        red "已取消部署"
        exit 1
      fi
    else
      green "本地镜像已存在"
    fi
  fi

  if [[ $is_update -eq 0 ]]; then
    green "[3/10] 创建实例目录"
    mkdir -p "${target_dir}/config" "${target_dir}/workspace"
    chown -R 1000:1000 "${target_dir}"
    CREATED_DIR=1
    TARGET_DIR="${target_dir}"
  else
    green "[3/10] 跳过目录创建（更新模式）"
  fi

  green "[4/10] 生成 compose.yaml"
  write_compose_file "$target_dir" "$project_name" "$image" "$timezone" "$ui_port" "$bridge_port"

  green "[5/10] 校验 compose"
  (
    cd "$target_dir"
    docker compose config >/dev/null
  )

  if [[ $is_update -eq 0 ]]; then
    green "[6/10] 执行 onboard"
    (
      cd "$target_dir"
      docker compose run --rm --no-deps --entrypoint node openclaw-gateway \
        dist/index.js onboard --mode local --no-install-daemon
    )
  else
    green "[6/10] 跳过 onboard（更新模式）"
  fi

  # 保存元数据
  set_metadata_value "$metadata_file" INSTANCE_NAME "$short_name"
  set_metadata_value "$metadata_file" PROJECT_NAME "$project_name"
  set_metadata_value "$metadata_file" DOMAIN "$domain"
  set_metadata_value "$metadata_file" GATEWAY_PORT "$ui_port"
  set_metadata_value "$metadata_file" BRIDGE_PORT "$bridge_port"
  set_metadata_value "$metadata_file" IMAGE "$image"
  set_metadata_value "$metadata_file" TIMEZONE "$timezone"
  set_metadata_value "$metadata_file" USE_GIT "$use_git"
  if [[ $use_git -eq 1 ]]; then
    set_metadata_value "$metadata_file" GIT_REPO "$git_repo"
    set_metadata_value "$metadata_file" GIT_BRANCH "$git_branch"
  fi

  local allowed_origins_json
  allowed_origins_json="$(build_allowed_origins_json "$domain" "$ui_port")"
  local batch_json
  batch_json="$(printf '[{"path":"gateway.mode","value":"local"},{"path":"gateway.bind","value":"lan"},{"path":"gateway.controlUi.allowedOrigins","value":%s}]' "$allowed_origins_json")"

  green "[7/10] 写入 gateway 配置"
  (
    cd "$target_dir"
    docker compose run --rm --no-deps --entrypoint node openclaw-gateway \
      dist/index.js config set --batch-json "$batch_json"
  )

  green "[8/10] 启动 openclaw-gateway"
  (
    cd "$target_dir"
    if [[ $is_update -eq 1 ]]; then
      # 更新模式：重启容器以应用新配置
      docker compose up -d openclaw-gateway
      green "已重启容器以应用新配置"
    else
      # 新建模式：首次启动
      docker compose up -d openclaw-gateway
    fi
  )

  # 安装 openclaw-lark 插件（必须在容器启动后）
  if [[ $install_lark -eq 1 ]]; then
    green "[8.5/10] 安装 openclaw-lark 插件"
    local lark_source="${base_dir}/openclaw-lark-source"
    local plugin_output="${target_dir}/temp-plugin-build"

    if ! ensure_lark_plugin "$lark_source" "$LARK_PLUGIN_REPO" "$LARK_PLUGIN_BRANCH"; then
      yellow "插件源码准备失败，跳过插件安装"
      yellow "你可以稍后手动安装插件"
    else
      if ! build_lark_plugin "$lark_source" "$plugin_output"; then
        yellow "插件构建失败，跳过插件安装"
        yellow "你可以稍后手动安装插件"
      else
        # 安装插件到实例
        if ! install_lark_plugin_to_instance "$target_dir" "${plugin_output}/openclaw-lark.tgz"; then
          yellow "插件安装失败"
          yellow "你可以稍后手动安装插件"
        else
          green "openclaw-lark 插件已安装"
        fi
      fi

      # 清理临时构建目录
      rm -rf "$plugin_output"
    fi
  fi

  green "[9/10] 生成辅助文件"
  write_nginx_snippet "$target_dir" "$domain" "$ui_port"
  write_readme "$target_dir" "$project_name" "$domain" "$ui_port" "$bridge_port"

  green "[10/10] 等待健康检查"
  health_wait "$ui_port"

  echo
  if [[ $is_update -eq 1 ]]; then
    green "================ 更新完成 ================"
    echo "操作模式       : 更新现有实例"
  else
    green "================ 部署完成 ================"
    echo "操作模式       : 新建实例"
  fi
  echo "项目名         : ${project_name}"
  echo "实例目录       : ${target_dir}"
  echo "Compose 文件   : ${target_dir}/compose.yaml"
  echo "Nginx 配置片段 : ${target_dir}/nginx-${domain}.conf"
  echo "说明文件       : ${target_dir}/README-BT.txt"
  echo "元数据文件     : ${metadata_file}"
  echo "本机调试地址   : http://127.0.0.1:${ui_port}"
  echo "正式访问地址   : https://${domain}"
  echo "========================================="
  echo

  if [[ $is_update -eq 0 ]]; then
    yellow "接下来需要做："
    echo "1) DNS 添加 A 记录：${domain} -> 你的服务器 IP"
    echo "2) 宝塔 -> 网站：创建站点 ${domain}"
    echo "3) 给站点申请 SSL"
    echo "4) 把 ${target_dir}/nginx-${domain}.conf 里的 location 配置粘到站点 Nginx 配置"
    echo
  else
    yellow "配置已更新："
    echo "- 如果域名变更，请更新 DNS 记录和宝塔站点配置"
    echo "- 如果端口变更，请更新 Nginx 反向代理配置"
    echo "- 容器已自动重启以应用新配置"
    echo
  fi

  if ask_yes_no "现在打印 Nginx 配置片段" "y"; then
    echo
    cat "${target_dir}/nginx-${domain}.conf"
    echo
  fi

  if ask_yes_no "现在打印常用运维命令" "y"; then
    echo
    echo "cd ${target_dir}"
    echo "docker compose ps"
    echo "docker compose logs -f openclaw-gateway"
    echo "docker compose run --rm openclaw-cli dashboard --no-open"
    echo "docker compose run --rm openclaw-cli devices list"
    echo "docker compose run --rm openclaw-cli devices approve <requestId>"
    echo
  fi

  yellow "说明："
  echo "- 这个脚本支持新增实例和更新现有实例配置。"
  echo "- 更新模式会保留现有的 config 和 workspace 数据。"
  echo "- 宝塔 Docker 里至少能看到容器；若未自动显示到容器编排，可导入 ${target_dir}/compose.yaml。"
  echo
}

main "$@"