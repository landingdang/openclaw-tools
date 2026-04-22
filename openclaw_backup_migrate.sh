#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

log() {
  printf '[%s] %s\n' "${SCRIPT_NAME}" "$*" >&2
}

die() {
  log "错误: $*"
  exit 1
}

progress() {
  local current="$1"
  local total="$2"
  local message="$3"
  local percent=$((current * 100 / total))
  local filled=$((percent / 2))
  local empty=$((50 - filled))
  printf '\r[%s%s] %d%% %s' "$(printf '#%.0s' $(seq 1 $filled))" "$(printf ' %.0s' $(seq 1 $empty))" "$percent" "$message" >&2
  if [[ $current -eq $total ]]; then
    printf '\n' >&2
  fi
}

resolve_state_dir() {
  local explicit_state_dir="${1:-}"
  local profile_name="${2:-}"

  if [[ -n "${explicit_state_dir}" ]]; then
    printf '%s\n' "${explicit_state_dir}"
    return
  fi
  if [[ -n "${OPENCLAW_STATE_DIR:-}" ]]; then
    printf '%s\n' "${OPENCLAW_STATE_DIR}"
    return
  fi
  if [[ -n "${profile_name}" ]]; then
    printf '%s\n' "${HOME}/.openclaw-${profile_name}"
    return
  fi
  printf '%s\n' "${HOME}/.openclaw"
}

resolve_config_path() {
  local state_dir="$1"
  local explicit_config_path="${2:-}"

  if [[ -n "${explicit_config_path}" ]]; then
    printf '%s\n' "${explicit_config_path}"
    return
  fi
  if [[ -n "${OPENCLAW_CONFIG_PATH:-}" ]]; then
    printf '%s\n' "${OPENCLAW_CONFIG_PATH}"
    return
  fi
  printf '%s\n' "${state_dir}/openclaw.json"
}

utc_timestamp() {
  date -u '+%Y%m%dT%H%M%SZ'
}

build_archive_path() {
  local output_target="${1:-}"
  local state_dir="$2"
  local timestamp
  local base_name

  timestamp="$(utc_timestamp)"
  base_name="$(basename "${state_dir}")"

  if [[ -z "${output_target}" ]]; then
    printf '%s\n' "${PWD}/${timestamp}-${base_name}-backup.tar.gz"
    return
  fi

  if [[ -d "${output_target}" || "${output_target%/}" != "${output_target}" ]]; then
    mkdir -p "${output_target}"
    printf '%s\n' "${output_target%/}/${timestamp}-${base_name}-backup.tar.gz"
    return
  fi

  mkdir -p "$(dirname "${output_target}")"
  printf '%s\n' "${output_target}"
}

sanitize_workspace_key() {
  local raw="${1:-workspace}"
  local sanitized
  sanitized="$(printf '%s' "${raw}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9._-]+/-/g; s/^-+//; s/-+$//')"
  if [[ -z "${sanitized}" ]]; then
    sanitized="workspace"
  fi
  printf '%s\n' "${sanitized}"
}

discover_external_workspaces() {
  local config_path="$1"
  local state_dir="$2"

  python3 - "$config_path" "$state_dir" <<'PY'
import json
import os
import sys
from pathlib import Path

config_path = Path(sys.argv[1]).expanduser()
state_dir = Path(sys.argv[2]).expanduser().resolve()
rows = []

if not config_path.is_file():
    print("[]")
    raise SystemExit(0)

with config_path.open() as handle:
    data = json.load(handle)

agents = ((data.get("agents") or {}).get("list") or []) if isinstance(data, dict) else []
seen = {}

for agent in agents:
    if not isinstance(agent, dict):
        continue
    workspace = agent.get("workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        continue
    resolved = Path(workspace).expanduser().resolve()
    try:
        common = os.path.commonpath([str(state_dir), str(resolved)])
    except ValueError:
        common = ""
    if common == str(state_dir):
        continue
    key = agent.get("id") or resolved.name or "workspace"
    slug = "".join(ch.lower() if ch.isalnum() or ch in "._-" else "-" for ch in str(key)).strip("-") or "workspace"
    if slug in seen:
        continue
    seen[slug] = True
    rows.append({"key": slug, "original_path": str(resolved)})

print(json.dumps(rows, ensure_ascii=False))
PY
}

write_manifest() {
  local manifest_path="$1"
  local state_dir="$2"
  local config_path="$3"
  local workspace_json="$4"
  local include_external_config="$5"

  python3 - "$manifest_path" "$state_dir" "$config_path" "$workspace_json" "$include_external_config" <<'PY'
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

manifest_path = Path(sys.argv[1])
state_dir = Path(sys.argv[2]).expanduser().resolve()
config_path = Path(sys.argv[3]).expanduser().resolve()
workspaces = json.loads(sys.argv[4])
include_external_config = sys.argv[5] == "1"

manifest = {
    "version": 1,
    "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "hostname": socket.gethostname(),
    "source_state_dir": str(state_dir),
    "source_config_path": str(config_path),
    "state_archive_root": f"state/{state_dir.name}",
    "config_archive_path": f"config/{config_path.name}" if include_external_config else "",
    "external_workspaces": workspaces,
}

manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

create_backup_archive() {
  local archive_path="$1"
  local state_dir="$2"
  local config_path="$3"
  local workspace_json="$4"
  local include_external_config="$5"

  log "开始创建备份归档..."
  progress 1 5 "准备清单文件"

  local temp_dir
  local manifest_path
  temp_dir="$(mktemp -d)"
  manifest_path="${temp_dir}/manifest.json"
  write_manifest "${manifest_path}" "${state_dir}" "${config_path}" "${workspace_json}" "${include_external_config}"

  progress 2 5 "打包状态目录"

  python3 - "$archive_path" "$manifest_path" "$state_dir" "$config_path" "$workspace_json" "$include_external_config" <<'PY'
import json
import sys
import tarfile
from pathlib import Path

archive_path = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
state_dir = Path(sys.argv[3]).expanduser().resolve()
config_path = Path(sys.argv[4]).expanduser().resolve()
workspaces = json.loads(sys.argv[5])
include_external_config = sys.argv[6] == "1"

with tarfile.open(archive_path, "w:gz") as tar:
    tar.add(manifest_path, arcname="manifest.json")
    tar.add(state_dir, arcname=f"state/{state_dir.name}")
    if include_external_config and config_path.exists():
        tar.add(config_path, arcname=f"config/{config_path.name}")
    for workspace in workspaces:
        workspace_path = Path(workspace["original_path"])
        if not workspace_path.exists():
            print(f"Warning: workspace not found, skipping: {workspace_path}", file=sys.stderr)
            continue
        tar.add(workspace["original_path"], arcname=f"workspaces/{workspace['key']}")
PY

  progress 5 5 "备份完成"
  rm -rf "${temp_dir}"
}

verify_backup_archive() {
  local archive_path="$1"

  log "验证归档文件..."

  python3 - "$archive_path" <<'PY'
import json
import sys
import tarfile

archive_path = sys.argv[1]
with tarfile.open(archive_path, "r:gz") as tar:
    names = tar.getnames()
    if "manifest.json" not in names:
        raise SystemExit("归档中缺少 manifest.json")
    manifest = json.load(tar.extractfile("manifest.json"))
    state_root = manifest.get("state_archive_root")
    if not state_root or not any(name == state_root or name.startswith(state_root + "/") for name in names):
        raise SystemExit("归档中缺少状态目录")
    config_archive_path = manifest.get("config_archive_path", "")
    if config_archive_path and config_archive_path not in names:
        raise SystemExit("归档中缺少外部配置文件")
    for workspace in manifest.get("external_workspaces", []):
        root = f"workspaces/{workspace['key']}"
        if not any(name == root or name.startswith(root + "/") for name in names):
            raise SystemExit(f"归档中缺少工作空间: {root}")
print("验证通过")
PY
}

sync_tree() {
  local source_dir="$1"
  local target_dir="$2"

  mkdir -p "${target_dir}"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a "${source_dir}/" "${target_dir}/"
  else
    cp -a "${source_dir}/." "${target_dir}/"
  fi
}

rewrite_workspace_paths() {
  local config_path="$1"
  local workspace_map_json="$2"

  python3 - "$config_path" "$workspace_map_json" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
workspace_map = json.loads(sys.argv[2])

if not config_path.is_file():
    raise SystemExit(0)

with config_path.open() as handle:
    data = json.load(handle)

changed = False
for agent in ((data.get("agents") or {}).get("list") or []):
    if not isinstance(agent, dict):
        continue
    current = agent.get("workspace")
    if current in workspace_map:
        agent["workspace"] = workspace_map[current]
        changed = True

if changed:
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

restore_backup_archive() {
  local archive_path="$1"
  local target_state_dir="$2"
  local target_config_path="$3"
  local workspace_root="$4"
  local overwrite_existing="$5"
  local run_doctor="$6"
  local restart_gateway="$7"

  log "开始恢复备份..."
  progress 1 6 "解压归档文件"

  local temp_dir
  local manifest_json
  temp_dir="$(mktemp -d)"

  python3 - "$archive_path" "$temp_dir" <<'PY'
import sys
import tarfile
from pathlib import Path

archive_path = Path(sys.argv[1])
temp_dir = Path(sys.argv[2])

with tarfile.open(archive_path, "r:gz") as tar:
    for member in tar.getmembers():
        if member.name.startswith("/") or ".." in Path(member.name).parts:
            raise SystemExit(f"unsafe archive member: {member.name}")
    tar.extractall(temp_dir, filter='data')
PY

  progress 2 6 "读取清单文件"

  manifest_json="$(python3 - "$temp_dir" <<'PY'
import json
import sys
from pathlib import Path

temp_dir = Path(sys.argv[1])
manifest = json.loads((temp_dir / "manifest.json").read_text(encoding="utf-8"))
print(json.dumps(manifest, ensure_ascii=False))
PY
)"

  local state_archive_root
  state_archive_root="$(python3 - "${manifest_json}" <<'PY'
import json, sys
print(json.loads(sys.argv[1])["state_archive_root"])
PY
)"

  local extracted_state_dir="${temp_dir}/${state_archive_root}"
  [[ -d "${extracted_state_dir}" ]] || die "归档中缺少状态目录: ${state_archive_root}"

  progress 3 6 "检查目标目录"

  if [[ -e "${target_state_dir}" && "${overwrite_existing}" != "1" ]]; then
    die "目标状态目录已存在: ${target_state_dir} (使用 --overwrite 覆盖)"
  fi
  if [[ -e "${target_state_dir}" && "${overwrite_existing}" == "1" ]]; then
    mv "${target_state_dir}" "${target_state_dir}.pre-restore.$(utc_timestamp)"
  fi

  progress 4 6 "恢复状态目录"

  sync_tree "${extracted_state_dir}" "${target_state_dir}"

  progress 5 6 "恢复工作空间"

  python3 - "${manifest_json}" "${temp_dir}" "${workspace_root}" "${target_config_path}" <<'PY'
import json
import shutil
import sys
from pathlib import Path

manifest = json.loads(sys.argv[1])
temp_dir = Path(sys.argv[2])
workspace_root = Path(sys.argv[3]).expanduser().resolve()
config_path = Path(sys.argv[4]).expanduser()
workspace_root.mkdir(parents=True, exist_ok=True)

workspace_map = {}
for workspace in manifest.get("external_workspaces", []):
    key = workspace["key"]
    source = temp_dir / "workspaces" / key
    if not source.exists():
        print(f"Warning: workspace not found in archive, skipping: {key}", file=sys.stderr)
        continue
    target = workspace_root / key
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    workspace_map[workspace["original_path"]] = str(target)

if config_path.is_file() and workspace_map:
    with config_path.open() as handle:
        data = json.load(handle)
    changed = False
    normalized_workspace_map = {
        str(Path(original).expanduser().resolve()): target
        for original, target in workspace_map.items()
    }
    for agent in ((data.get("agents") or {}).get("list") or []):
        if not isinstance(agent, dict):
            continue
        current = agent.get("workspace")
        if not isinstance(current, str) or not current.strip():
            continue
        current_resolved = str(Path(current).expanduser().resolve())
        if current_resolved in normalized_workspace_map:
            agent["workspace"] = normalized_workspace_map[current_resolved]
            changed = True
    if changed:
        config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
PY

  if [[ "${run_doctor}" == "1" ]]; then
    if command -v openclaw >/dev/null 2>&1; then
      openclaw doctor || true
    fi
  fi
  if [[ "${restart_gateway}" == "1" ]]; then
    if command -v openclaw >/dev/null 2>&1; then
      openclaw gateway restart || true
    fi
  fi

  progress 6 6 "恢复完成"

  rm -rf "${temp_dir}"
}

maybe_stop_gateway() {
  if command -v openclaw >/dev/null 2>&1; then
    openclaw gateway stop || true
  fi
}

usage() {
  cat <<'EOF'
用法:
  openclaw_backup_migrate.sh backup [选项]
  openclaw_backup_migrate.sh verify --archive 文件
  openclaw_backup_migrate.sh restore --archive 文件 [选项]

备份选项:
  --state-dir DIR         覆盖 OpenClaw 状态目录 (默认: OPENCLAW_STATE_DIR 或 ~/.openclaw)
  --config-path FILE      覆盖配置文件路径 (默认: OPENCLAW_CONFIG_PATH 或 <state-dir>/openclaw.json)
  --profile NAME          当未指定 --state-dir 时使用 ~/.openclaw-NAME
  --output PATH           输出归档文件或目录
  --no-include-workspace  跳过 agents.list 中的外部工作空间
  --no-stop-gateway       备份前不尝试执行 `openclaw gateway stop`
  --verify                写入后验证归档文件
  --dry-run               仅打印备份计划

恢复选项:
  --archive FILE          由此脚本创建的备份归档
  --state-dir DIR         新机器上的目标状态目录
  --config-path FILE      目标配置路径 (默认: <state-dir>/openclaw.json)
  --profile NAME          当未指定 --state-dir 时使用 ~/.openclaw-NAME
  --workspace-root DIR    在此根目录下恢复外部工作空间 (默认: <state-dir>/external-workspaces)
  --overwrite             移动现有目标状态目录并覆盖恢复
  --skip-doctor           恢复后不运行 `openclaw doctor`
  --skip-restart          恢复后不运行 `openclaw gateway restart`
  --dry-run               仅打印恢复计划
EOF
}

main() {
  [[ $# -ge 1 ]] || { usage; exit 1; }

  command -v python3 >/dev/null 2>&1 || die "需要 python3 但在 PATH 中未找到"

  local command="$1"
  shift

  case "${command}" in
    backup)
      local state_dir="" config_path="" profile_name="" output_target=""
      local include_workspace="1" stop_gateway="1" verify_after="0" dry_run="0"
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --state-dir) state_dir="$2"; shift 2 ;;
          --config-path) config_path="$2"; shift 2 ;;
          --profile) profile_name="$2"; shift 2 ;;
          --output) output_target="$2"; shift 2 ;;
          --no-include-workspace) include_workspace="0"; shift ;;
          --no-stop-gateway) stop_gateway="0"; shift ;;
          --verify) verify_after="1"; shift ;;
          --dry-run) dry_run="1"; shift ;;
          -h|--help) usage; exit 0 ;;
          *) die "未知的备份选项: $1" ;;
        esac
      done
      state_dir="$(resolve_state_dir "${state_dir}" "${profile_name}")"
      config_path="$(resolve_config_path "${state_dir}" "${config_path}")"
      [[ -d "${state_dir}" ]] || die "状态目录未找到: ${state_dir}"
      local archive_path
      archive_path="$(build_archive_path "${output_target}" "${state_dir}")"
      local workspace_json='[]'
      if [[ "${include_workspace}" == "1" ]]; then
        workspace_json="$(discover_external_workspaces "${config_path}" "${state_dir}")"
      fi
      local include_external_config="0"
      if [[ -f "${config_path}" ]]; then
        local resolved_state_dir resolved_config_path common_path
        resolved_state_dir="$(python3 - "${state_dir}" <<'PY'
import pathlib, sys
print(pathlib.Path(sys.argv[1]).expanduser().resolve())
PY
)"
        resolved_config_path="$(python3 - "${config_path}" <<'PY'
import pathlib, sys
print(pathlib.Path(sys.argv[1]).expanduser().resolve())
PY
)"
        common_path="$(python3 - "${resolved_state_dir}" "${resolved_config_path}" <<'PY'
import os, sys
try:
    common = os.path.commonpath([sys.argv[1], sys.argv[2]])
    print(common)
except ValueError:
    print("")
PY
)"
        if [[ "${common_path}" != "${resolved_state_dir}" ]]; then
          include_external_config="1"
        fi
      fi
      if [[ "${dry_run}" == "1" ]]; then
        printf '状态目录=%s\n配置路径=%s\n归档文件=%s\n包含工作空间=%s\n工作空间列表=%s\n' \
          "${state_dir}" "${config_path}" "${archive_path}" "${include_workspace}" "${workspace_json}"
        exit 0
      fi
      if [[ "${stop_gateway}" == "1" ]]; then
        maybe_stop_gateway
      fi
      create_backup_archive "${archive_path}" "${state_dir}" "${config_path}" "${workspace_json}" "${include_external_config}"
      if [[ "${verify_after}" == "1" ]]; then
        verify_backup_archive "${archive_path}"
      fi
      log "备份已创建: ${archive_path}"
      printf '%s\n' "${archive_path}"
      ;;
    verify)
      local archive_path=""
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --archive) archive_path="$2"; shift 2 ;;
          -h|--help) usage; exit 0 ;;
          *) die "未知的验证选项: $1" ;;
        esac
      done
      [[ -n "${archive_path}" ]] || die "验证需要 --archive 参数"
      verify_backup_archive "${archive_path}"
      ;;
    restore)
      local archive_path="" state_dir="" config_path="" profile_name="" workspace_root=""
      local overwrite_existing="0" run_doctor="1" restart_gateway="1" dry_run="0"
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --archive) archive_path="$2"; shift 2 ;;
          --state-dir) state_dir="$2"; shift 2 ;;
          --config-path) config_path="$2"; shift 2 ;;
          --profile) profile_name="$2"; shift 2 ;;
          --workspace-root) workspace_root="$2"; shift 2 ;;
          --overwrite) overwrite_existing="1"; shift ;;
          --skip-doctor) run_doctor="0"; shift ;;
          --skip-restart) restart_gateway="0"; shift ;;
          --dry-run) dry_run="1"; shift ;;
          -h|--help) usage; exit 0 ;;
          *) die "未知的恢复选项: $1" ;;
        esac
      done
      [[ -n "${archive_path}" ]] || die "恢复需要 --archive 参数"
      state_dir="$(resolve_state_dir "${state_dir}" "${profile_name}")"
      config_path="$(resolve_config_path "${state_dir}" "${config_path}")"
      workspace_root="${workspace_root:-${state_dir}/external-workspaces}"
      if [[ "${dry_run}" == "1" ]]; then
        printf '归档文件=%s\n目标状态目录=%s\n目标配置路径=%s\n工作空间根目录=%s\n覆盖=%s\n' \
          "${archive_path}" "${state_dir}" "${config_path}" "${workspace_root}" "${overwrite_existing}"
        exit 0
      fi
      restore_backup_archive "${archive_path}" "${state_dir}" "${config_path}" "${workspace_root}" "${overwrite_existing}" "${run_doctor}" "${restart_gateway}"
      log "恢复完成: ${state_dir}"
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
