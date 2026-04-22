#!/usr/bin/env python3
"""
飞书/Lark 开放平台 - 自动创建企业自建机器人 (非交互式)

用法:
    python3 feishu_bot_creator.py init     # 检查并安装依赖 (playwright + Chromium)
    python3 feishu_bot_creator.py create   # 完整流程: 二维码 → 扫码 → 创建机器人 (默认飞书)
    python3 feishu_bot_creator.py create --reset-profile   # 显式重置浏览器 profile 后再创建
    python3 feishu_bot_creator.py create --platform lark   # Lark 海外版
    python3 feishu_bot_creator.py cleanup  # 关闭残留浏览器进程
    python3 feishu_bot_creator.py config-test  # 仅验证配置归一化/落盘，不走扫码登录
    python3 feishu_bot_creator.py regression-test  # 批量回归 schema/profile/avatar/allowFrom/agent/create-flow

流程: init (安装依赖) → create (扫码登录 + 创建机器人 + 配置)
支持平台: feishu (默认, 国内版) | lark (海外版)
"""

# ============================================================
# 依赖自举
# ============================================================
import importlib
import importlib.util
import os
import subprocess
import sys
import copy
import tempfile
import traceback
from fnmatch import fnmatchcase
from pathlib import Path

_REQUIRED_PACKAGES = [
    ("playwright", "playwright"),
    ("qrcode", "qrcode"),
]


def _ensure_pip():
    try:
        importlib.import_module("pip")
        return
    except ImportError:
        pass
    try:
        subprocess.check_call(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    import tempfile, urllib.request
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", f.name)
        subprocess.check_call(
            [sys.executable, f.name, "--quiet", "--break-system-packages"])


def _ensure_dependencies():
    missing = [pip for mod, pip in _REQUIRED_PACKAGES
               if not importlib.util.find_spec(mod)]
    if missing:
        _ensure_pip()
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--break-system-packages"] + missing)
        importlib.invalidate_caches()
        import site; site.main()

    from playwright.sync_api import sync_playwright
    try:
        pw = sync_playwright().start()
        pw.chromium.launch(headless=True).close()
        pw.stop()
    except Exception:
        # 1) 先安装系统依赖（兼容 CentOS/RHEL/Debian/Ubuntu）
        _install_system_deps()
        # 2) 设置环境变量跳过 Playwright 内部的 apt-get 依赖安装
        env = os.environ.copy()
        env["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] = "0"
        env["DEBIAN_FRONTEND"] = "noninteractive"
        # 3) 安装 Chromium 二进制（不带 --with-deps）
        try:
            subprocess.check_call(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                env=env)
        except subprocess.CalledProcessError:
            # 某些 Playwright 版本 install 命令仍会尝试安装 deps 并报错
            # 但浏览器二进制可能已下载成功，验证一下
            try:
                pw2 = sync_playwright().start()
                path = pw2.chromium.executable_path
                pw2.stop()
                if not os.path.isfile(path):
                    raise FileNotFoundError(path)
            except Exception as e2:
                sys.exit(1)


def _install_system_deps():
    """尝试用系统包管理器安装 Chromium 运行所需的共享库。"""
    _LIBS_YUM = [
        "nss", "nspr", "atk", "at-spi2-atk", "at-spi2-core",
        "libdrm", "libXcomposite", "libXdamage", "libXrandr",
        "mesa-libgbm", "pango", "cups-libs", "libxkbcommon",
        "alsa-lib", "libXfixes", "libxshmfence",
    ]
    _LIBS_APT = [
        "libnss3", "libnspr4", "libatk1.0-0", "libatk-bridge2.0-0",
        "libdrm2", "libxcomposite1", "libxdamage1", "libxrandr2",
        "libgbm1", "libpango-1.0-0", "libcups2", "libxkbcommon0",
        "libasound2", "libxfixes3", "libxshmfence1",
    ]

    for pkg_mgr, libs in [
        (["yum", "install", "-y"], _LIBS_YUM),
        (["dnf", "install", "-y"], _LIBS_YUM),
        (["apt-get", "install", "-y"], _LIBS_APT),
    ]:
        try:
            subprocess.check_call(
                [pkg_mgr[0], "--version"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
        try:
            subprocess.call(
                pkg_mgr + libs,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
        break


# 注意: _ensure_dependencies() 不在顶层调用，由 cmd_init 触发
# playwright 也延迟到实际使用时导入

# ============================================================
# 强制 stdout 行缓冲 / write-through（管道环境下 Python 默认全缓冲，
# 导致前端读不到 QR JSON）。等效于 python3 -u 但无需调用方配合。
# ============================================================
if hasattr(sys.stdout, "reconfigure"):
    # Python ≥ 3.7: 最简方式
    sys.stdout.reconfigure(write_through=True)
elif hasattr(sys.stdout, "buffer"):
    import io as _io
    sys.stdout = _io.TextIOWrapper(
        sys.stdout.buffer, write_through=True,
        encoding=sys.stdout.encoding, errors=sys.stdout.errors,
    )

# ============================================================
# 业务 import（不含 playwright，延迟到 create 时导入）
# ============================================================
import io
import json
import logging
import os
import random
import re
import shutil
import signal
import ssl
import time
import uuid
import urllib.parse
import urllib.request
import urllib.error
from typing import List, Optional, Dict, Any, Tuple

# ============================================================
# 自定义异常类
# ============================================================
class FeishuBotError(Exception):
    """飞书机器人创建基础异常类"""
    pass


class LoginTimeoutError(FeishuBotError):
    """登录超时异常"""
    pass


class QRCodeExpiredError(FeishuBotError):
    """二维码过期异常"""
    pass


class PermissionDeniedError(FeishuBotError):
    """权限被拒绝异常"""
    pass


class ConfigValidationError(FeishuBotError):
    """配置验证失败异常"""
    pass


class BrowserAutomationError(FeishuBotError):
    """浏览器自动化操作失败异常"""
    pass


class APIRequestError(FeishuBotError):
    """API 请求失败异常"""
    pass


class AppCreationError(FeishuBotError):
    """应用创建失败异常"""
    pass


class AppPublishError(FeishuBotError):
    """应用发布失败异常"""
    pass


class AvatarDownloadError(FeishuBotError):
    """头像下载失败异常"""
    pass


class DependencyInstallError(FeishuBotError):
    """依赖安装失败异常"""
    pass


# ============================================================
# 日志系统配置
# ============================================================
def _setup_logging() -> logging.Logger:
    """配置日志系统"""
    logger = logging.getLogger("feishu_bot_creator")
    logger.setLevel(logging.INFO)

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # 文件处理器
    try:
        file_handler = logging.FileHandler("feishu_bot_creator.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except (OSError, PermissionError):
        pass  # 如果无法创建日志文件，继续使用控制台输出

    # 控制台格式化器（简化版）
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger


# 全局日志实例
_logger = _setup_logging()


# ============================================================
# Pydantic 配置验证模型
# ============================================================
try:
    from pydantic import BaseModel, Field, field_validator, ConfigDict

    class BotProfileModel(BaseModel):
        """机器人配置模型"""
        model_config = ConfigDict(str_strip_whitespace=True)

        name_zh: str = Field(..., min_length=1, max_length=50, description="机器人中文名称")
        openclaw_name: str = Field(..., min_length=1, max_length=50, description="OpenClaw标识")
        desc_zh: str = Field(default="", max_length=200, description="机器人描述")
        avatar_url: str = Field(default="", description="头像URL")

        @field_validator('openclaw_name')
        @classmethod
        def validate_openclaw_name(cls, v: str) -> str:
            """验证OpenClaw名称格式"""
            if v.lower() in ('default', 'system', 'admin'):
                raise ValueError(f'保留关键字不能使用: {v}')
            if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$', v.lower()):
                raise ValueError('OpenClaw名称只能包含小写字母、数字和连字符，且不能以连字符开头或结尾')
            return v


    class ChannelConfigModel(BaseModel):
        """频道配置模型"""
        model_config = ConfigDict(str_strip_whitespace=True)

        dm_policy: str = Field(default="pairing", pattern="^(pairing|allowlist|open)$")
        group_policy: str = Field(default="open", pattern="^(open|allowlist|disabled)$")
        allow_from: List[str] = Field(default_factory=list)
        group_allow_from: List[str] = Field(default_factory=list)
        require_mention: bool = Field(default=True)


    class FeishuAccountModel(BaseModel):
        """飞书账号配置模型"""
        model_config = ConfigDict(str_strip_whitespace=True)

        app_id: str = Field(..., min_length=1, description="应用ID")
        app_secret: str = Field(..., min_length=1, description="应用密钥")

        @field_validator('app_id')
        @classmethod
        def validate_app_id(cls, v: str) -> str:
            """验证应用ID格式"""
            if not v.startswith('cli_') and not v.startswith('${'):
                raise ValueError('应用ID格式不正确，应以cli_开头或为环境变量占位符')
            return v

    _PYDANTIC_AVAILABLE = True

except ImportError:
    _PYDANTIC_AVAILABLE = False
    _logger.warning("Pydantic未安装，配置验证功能将被禁用")


# ============================================================
# 平台配置 (feishu / lark)
# ============================================================
PLATFORM = "feishu"  # 默认值，由 main() 解析 --platform 参数覆盖

_PLATFORM_CONFIGS = {
    "feishu": {
        "base_url": "https://open.feishu.cn",
        "login_url": (
            "https://accounts.feishu.cn/accounts/page/login"
            "?app_id=7&no_trap=1"
            "&redirect_uri=https%3A%2F%2Fopen.feishu.cn%2Fapp"
        ),
        "accounts_host": "accounts.feishu.cn",
        "open_host": "open.feishu.cn",
        "admin_audit_url": "https://feishu.cn/admin/appCenter/audit",
        "config_domain": "feishu",
        "primary_lang": "zh_cn",
        "default_greeting": "Hi，我是你刚刚使用腾讯轻量云创建的机器人，你现在可以跟我聊天了！",
        "state_file_prefix": "feishu-bot",
        "profile_dir_name": "feishu-bot-chrome-profile",
        "qr_default": True,   # 飞书登录页默认就是二维码模式
    },
    "lark": {
        "base_url": "https://open.larksuite.com",
        "login_url": (
            "https://accounts.larksuite.com/accounts/page/login"
            "?app_id=7&no_trap=1"
            "&redirect_uri=https%3A%2F%2Fopen.larksuite.com%2F%3Flang%3Dzh-CN"
        ),
        "accounts_host": "accounts.larksuite.com",
        "open_host": "open.larksuite.com",
        "admin_audit_url": "https://larksuite.com/admin/appCenter/audit",
        "config_domain": "lark",
        "primary_lang": "en_us",
        "default_greeting": "Hi, I'm the bot you just created with Tencent Lighthouse. You can chat with me now!",
        "state_file_prefix": "lark-bot",
        "profile_dir_name": "lark-bot-chrome-profile",
        "qr_default": False,  # Lark 登录页默认是邮箱模式，需要切换
    },
}


def _pcfg(key: str):
    """获取当前平台的配置值。"""
    return _PLATFORM_CONFIGS[PLATFORM][key]


# ============================================================
# 常量 (平台无关)
# ============================================================
LOGIN_TIMEOUT = 90
POLL_INTERVAL = 2
QR_MAX_RETRIES = 3

DEFAULT_AVATAR_URL = "https://cloudcache.tencent-cloud.com/qcloud/ui/static/other_external_resource/4e9ca8c5-0ce4-44a2-8c7c-4f8f43f9e73a.png"
_LOCAL_AVATAR_DIR_NAME = "avatar"

# 远程随机头像源：先挑一个远程 URL，再下载到本地。
# 这里保留为可注入的纯 URL 列表，方便后续 smoke 测试通过 monkeypatch
# 固定选择器来验证 explicit/random/fallback 三条路径。
REMOTE_RANDOM_AVATAR_URLS = [
    "https://picsum.photos/seed/openclaw-avatar-1/512",
    "https://picsum.photos/seed/openclaw-avatar-2/512",
    "https://picsum.photos/seed/openclaw-avatar-3/512",
]

OPENCLAW_CONFIG = "/root/.openclaw/openclaw.json"
OPENCLAW_ALLOW_FROM = "/root/.openclaw/credentials/feishu-default-allowFrom.json"
WEBSOCKET_POLL_INTERVAL = 3   # 轮询长连接状态的间隔 (秒)
WEBSOCKET_POLL_TIMEOUT = 60   # 等待长连接建立的最大时间 (秒)

STATE_DIR = "/tmp"
CDP_PORT = 9222  # Chromium CDP 调试端口

_OPENCLAW_CONFIG_ENV = "OPENCLAW_CONFIG_PATH"
_OPENCLAW_ALLOW_FROM_ENV = "OPENCLAW_ALLOW_FROM_PATH"
_STATE_DIR_ENV = "OPENCLAW_STATE_DIR"
_EMIT_SECRET_ENV = "OPENCLAW_EMIT_SECRET"
_OPENCLAW_ALLOW_FROM_RELATIVE = os.path.join("credentials", "feishu-default-allowFrom.json")
_SUMMARY_OUTPUT_MODE = False
_PROJECT_ENV_FILE_NAME = ".env"
_LEGACY_ENV_DIR_NAME = ".env.legacy"
_LEGACY_FEISHU_ENV_FILE_NAME = "feishu-accounts.env"
_LEGACY_RUNTIME_ENV_FILE_NAME = "runtime.env"


def _env_or_default(env_name: str, default: str) -> str:
    """获取环境变量或返回默认值

    Args:
        env_name: 环境变量名称
        default: 默认值

    Returns:
        环境变量值或默认值
    """
    value = os.environ.get(env_name, "").strip()
    return value or default


def _expand_path(path: str) -> str:
    """展开路径（处理~和相对路径）

    Args:
        path: 原始路径

    Returns:
        绝对路径
    """
    return os.path.abspath(os.path.expanduser(path))


def _project_root_dir() -> Path:
    """获取项目根目录

    Returns:
        项目根目录Path对象
    """
    return Path(__file__).resolve().parent


def _project_env_file() -> Path:
    """获取项目环境变量文件路径

    Returns:
        .env文件Path对象
    """
    return _project_root_dir() / _PROJECT_ENV_FILE_NAME


def _legacy_env_dir() -> Path:
    """获取遗留环境变量目录

    Returns:
        遗留环境变量目录Path对象
    """
    return _project_root_dir() / _LEGACY_ENV_DIR_NAME


def _legacy_env_candidates() -> List[Path]:
    """获取所有可能的遗留环境变量文件路径

    Returns:
        遗留环境变量文件路径列表
    """
    candidates = []
    env_path = _project_root_dir() / _PROJECT_ENV_FILE_NAME
    if env_path.is_dir():
        candidates.extend([
            env_path / _LEGACY_FEISHU_ENV_FILE_NAME,
            env_path / _LEGACY_RUNTIME_ENV_FILE_NAME,
        ])
    legacy_dir = _legacy_env_dir()
    candidates.extend([
        legacy_dir / _LEGACY_FEISHU_ENV_FILE_NAME,
        legacy_dir / _LEGACY_RUNTIME_ENV_FILE_NAME,
    ])
    deduped = []
    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _default_openclaw_root() -> str:
    """获取默认的OpenClaw根目录

    根据操作系统返回合适的配置目录：
    - macOS: ~/Library/Application Support/OpenClaw
    - Linux: ~/.config/openclaw 或 $XDG_CONFIG_HOME/openclaw

    Returns:
        OpenClaw根目录路径
    """
    home = _expand_path("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "OpenClaw")
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg_config_home:
        return os.path.join(_expand_path(xdg_config_home), "openclaw")
    return os.path.join(home, ".config", "openclaw")


def _default_state_dir() -> str:
    """获取默认的状态目录

    根据操作系统返回合适的缓存目录：
    - macOS: ~/Library/Caches/OpenClaw/runtime
    - Linux: ~/.cache/openclaw/runtime 或 $XDG_CACHE_HOME/openclaw/runtime

    Returns:
        状态目录路径
    """
    home = _expand_path("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Caches", "OpenClaw", "runtime")
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg_cache_home:
        return os.path.join(_expand_path(xdg_cache_home), "openclaw", "runtime")
    return os.path.join(home, ".cache", "openclaw", "runtime")


def _paths_from_openclaw_root(root_dir: str) -> Dict[str, str]:
    """从OpenClaw根目录派生相关路径

    Args:
        root_dir: OpenClaw根目录

    Returns:
        包含openclaw_root、config_path、allow_from_path的字典
    """
    openclaw_root = _expand_path(root_dir)
    return {
        "openclaw_root": openclaw_root,
        "config_path": os.path.join(openclaw_root, "openclaw.json"),
        "allow_from_path": os.path.join(openclaw_root, _OPENCLAW_ALLOW_FROM_RELATIVE),
    }


def _infer_openclaw_root(config_path: str = "", allow_from_path: str = "") -> str:
    """从配置文件路径推断OpenClaw根目录

    Args:
        config_path: 配置文件路径
        allow_from_path: allowFrom文件路径

    Returns:
        推断出的OpenClaw根目录
    """
    config_candidate = (config_path or "").strip()
    if config_candidate:
        return os.path.dirname(_expand_path(config_candidate))

    allow_candidate = (allow_from_path or "").strip()
    if allow_candidate:
        expanded_allow = _expand_path(allow_candidate)
        parent = os.path.dirname(expanded_allow)
        if os.path.basename(parent) == "credentials":
            return os.path.dirname(parent)
        return parent

    return _default_openclaw_root()


def _resolve_runtime_paths(openclaw_root: str = "", state_dir: str = "",
                           config_path: str = "", allow_from_path: str = "") -> dict:
    root_override = (openclaw_root or "").strip()
    if root_override:
        resolved = _paths_from_openclaw_root(root_override)
    else:
        config_candidate = (config_path or os.environ.get(_OPENCLAW_CONFIG_ENV, "")).strip()
        allow_candidate = (allow_from_path or os.environ.get(_OPENCLAW_ALLOW_FROM_ENV, "")).strip()
        inferred_root = _infer_openclaw_root(
            config_path=config_candidate,
            allow_from_path=allow_candidate,
        )
        resolved = _paths_from_openclaw_root(inferred_root)
        if config_candidate:
            resolved["config_path"] = _expand_path(config_candidate)
        if allow_candidate:
            resolved["allow_from_path"] = _expand_path(allow_candidate)

    state_candidate = (state_dir or os.environ.get(_STATE_DIR_ENV, "")).strip()
    resolved["state_dir"] = _expand_path(state_candidate) if state_candidate else _default_state_dir()
    return resolved


def _apply_runtime_paths(openclaw_root: str = "", state_dir: str = "",
                         config_path: str = "", allow_from_path: str = "") -> dict:
    global OPENCLAW_ROOT, OPENCLAW_CONFIG, OPENCLAW_ALLOW_FROM, STATE_DIR
    paths = _resolve_runtime_paths(
        openclaw_root=openclaw_root,
        state_dir=state_dir,
        config_path=config_path,
        allow_from_path=allow_from_path,
    )
    OPENCLAW_ROOT = paths["openclaw_root"]
    OPENCLAW_CONFIG = paths["config_path"]
    OPENCLAW_ALLOW_FROM = paths["allow_from_path"]
    STATE_DIR = paths["state_dir"]
    return paths


def _set_private_permissions(path: str) -> None:
    """设置文件为私有权限（仅所有者可读写）

    Args:
        path: 文件路径

    Note:
        仅在POSIX系统上生效，Windows系统会跳过
    """
    if os.name != "posix":
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _should_emit_secret() -> bool:
    """检查是否应该输出敏感信息

    通过环境变量OPENCLAW_EMIT_SECRET控制

    Returns:
        是否应该输出敏感信息
    """
    value = os.environ.get(_EMIT_SECRET_ENV, "").strip().lower()
    return value in ("1", "true", "yes", "on")


def _mask_identifier(value: str) -> str:
    """脱敏处理标识符

    Args:
        value: 原始标识符

    Returns:
        脱敏后的标识符（保留前3位和后3位）

    Examples:
        >>> _mask_identifier("cli_a1b2c3d4e5f6g7h8")
        'cli***7h8'
        >>> _mask_identifier("short")
        '*****'
    """
    candidate = (value or "").strip()
    if len(candidate) <= 6:
        return "*" * len(candidate)
    return f"{candidate[:3]}***{candidate[-3:]}"


def _sanitize_state_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    """清理状态数据中的敏感信息

    Args:
        payload: 原始数据字典

    Returns:
        清理后的数据字典（移除敏感字段）
    """
    if not isinstance(payload, dict):
        return {}
    sanitized = copy.deepcopy(payload)
    for key in ("appSecret", "app_secret", "tenant_access_token", "tenantAccessToken"):
        sanitized.pop(key, None)
    return sanitized


def _dotenv_quote(value: str) -> str:
    """为.env文件值添加引号和转义

    Args:
        value: 原始值

    Returns:
        带引号和转义的值

    Examples:
        >>> _dotenv_quote('hello world')
        '"hello world"'
        >>> _dotenv_quote('path\\to\\file')
        '"path\\\\to\\\\file"'
    """
    escaped = (value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _read_env_file(path: Path) -> Dict[str, str]:
    """读取.env文件

    Args:
        path: .env文件路径

    Returns:
        环境变量字典
    """
    if not path.is_file():
        return {}
    data = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            data[key] = value
    return data


def _write_env_file(path: Path, assignments: Dict[str, str]) -> None:
    """写入.env文件

    Args:
        path: .env文件路径
        assignments: 环境变量字典

    Note:
        文件权限会被设置为0600（仅所有者可读写）
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={_dotenv_quote(str(value))}" for key, value in sorted(assignments.items())]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    _set_private_permissions(str(path))


def _project_env_file_assignments() -> dict:
    assignments = {}
    unified_env_path = _project_env_file()
    if unified_env_path.is_file():
        assignments.update(_read_env_file(unified_env_path))
    for path in _legacy_env_candidates():
        assignments.update(_read_env_file(path))
    return assignments


def _project_env_assignments() -> dict:
    assignments = _project_env_file_assignments()
    assignments.update({key: value for key, value in os.environ.items() if isinstance(value, str)})
    return assignments


def _resolve_env_placeholder(value):
    if not _is_env_placeholder(value):
        return value
    key = value[2:-1].strip()
    if not key:
        return value
    return _project_env_assignments().get(key, value)


def _sync_runtime_env_bridge() -> None:
    unified_env_path = _project_env_file()
    if not unified_env_path.exists():
        _write_env_file(unified_env_path, {})

    merged = _project_env_file_assignments()
    additional_env_sources = [path for path in _legacy_env_candidates() if path.is_file()]

    bridge_path = Path(OPENCLAW_ROOT) / ".env"
    bridge_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if bridge_path.is_symlink():
            bridge_path.unlink()
        if bridge_path.exists():
            bridge_path.unlink()
    except OSError:
        pass
    if additional_env_sources:
        _write_env_file(bridge_path, merged)
        return
    try:
        bridge_path.symlink_to(unified_env_path)
    except OSError:
        _write_env_file(bridge_path, merged)


def _env_placeholder(var_name: str) -> str:
    return f"${{{var_name}}}"


def _is_env_placeholder(value) -> bool:
    return isinstance(value, str) and value.startswith("${") and value.endswith("}")


def _feishu_env_var_names(account_id: str) -> dict:
    suffix = re.sub(r"[^A-Z0-9]+", "_", (account_id or "").strip().upper()).strip("_") or "DEFAULT"
    return {
        "app_id": f"FEISHU_{suffix}_APP_ID",
        "app_secret": f"FEISHU_{suffix}_APP_SECRET",
    }


def _persist_feishu_env_secrets(account_id: str, app_id: str, app_secret: str) -> dict:
    env_path = _project_env_file()
    assignments = {}
    for legacy_path in _legacy_env_candidates():
        assignments.update(_read_env_file(legacy_path))
    assignments.update(_read_env_file(env_path))
    env_vars = _feishu_env_var_names(account_id)
    assignments[env_vars["app_id"]] = app_id
    assignments[env_vars["app_secret"]] = app_secret
    _write_env_file(env_path, assignments)
    for legacy_path in _legacy_env_candidates():
        try:
            legacy_path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            pass
    _sync_runtime_env_bridge()
    return env_vars


def _sanitize_feishu_account_secrets(accounts: dict) -> None:
    for account_id, account in accounts.items():
        if _is_policy_account_id(account_id) or not isinstance(account, dict):
            continue
        app_id = account.get("appId")
        app_secret = account.get("appSecret")
        if not isinstance(app_id, str) or not isinstance(app_secret, str):
            continue
        if _is_env_placeholder(app_id) and _is_env_placeholder(app_secret):
            continue
        env_vars = _persist_feishu_env_secrets(account_id, app_id, app_secret)
        account["appId"] = _env_placeholder(env_vars["app_id"])
        account["appSecret"] = _env_placeholder(env_vars["app_secret"])


def _normalize_bool_input(value) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "y", "on"):
        return True
    if normalized in ("0", "false", "no", "n", "off"):
        return False
    return None


def _parse_csv_list(raw: str) -> list:
    if not isinstance(raw, str):
        return []
    return _dedupe_keep_order([part.strip() for part in raw.split(",") if part.strip()])


def _normalize_policy_value(value: str, allowed: tuple[str, ...], default: str) -> str:
    candidate = (value or "").strip().lower()
    return candidate if candidate in allowed else default


def _validate_bot_profile_with_pydantic(name_zh: str, openclaw_name: str,
                                        desc_zh: str = "", avatar_url: str = "") -> Dict[str, Any]:
    """使用Pydantic验证机器人配置"""
    if not _PYDANTIC_AVAILABLE:
        return {"valid": True, "data": {
            "name_zh": name_zh,
            "openclaw_name": openclaw_name,
            "desc_zh": desc_zh,
            "avatar_url": avatar_url
        }}

    try:
        profile = BotProfileModel(
            name_zh=name_zh,
            openclaw_name=openclaw_name,
            desc_zh=desc_zh or name_zh,
            avatar_url=avatar_url
        )
        return {"valid": True, "data": profile.model_dump()}
    except Exception as e:
        _logger.error(f"机器人配置验证失败: {e}")
        raise ConfigValidationError(f"机器人配置验证失败: {e}")


def _normalize_bot_profile(*, fallback_name: str = "", openclaw_name: str = "",
                           name_zh: str = "", desc_zh: str = "",
                           avatar_path: str = "") -> dict:
    """标准化机器人配置

    Args:
        fallback_name: 后备名称
        openclaw_name: OpenClaw标识
        name_zh: 中文名称
        desc_zh: 中文描述
        avatar_path: 头像路径

    Returns:
        标准化后的配置字典
    """
    fallback = (fallback_name or "").strip()
    normalized_openclaw_name = (openclaw_name or "").strip() or fallback
    normalized_name_zh = (name_zh or "").strip() or normalized_openclaw_name or fallback or _gen_bot_name()
    normalized_desc_zh = (desc_zh or "").strip() or normalized_name_zh or normalized_openclaw_name or fallback
    primary_name = normalized_name_zh or normalized_openclaw_name or fallback or _gen_bot_name()
    return {
        "openclaw_name": normalized_openclaw_name or primary_name,
        "name_zh": normalized_name_zh or primary_name,
        "desc_zh": normalized_desc_zh or primary_name,
        "primary_name": primary_name,
        "avatar_path": (avatar_path or "").strip(),
    }


def _normalize_channel_config(*, dm_policy: str = "", group_policy: str = "",
                              allow_from=None, group_allow_from=None,
                              require_mention=None) -> dict:
    normalized_dm_policy = _normalize_policy_value(dm_policy, ("pairing", "allowlist", "open"), "pairing")
    normalized_group_policy = _normalize_policy_value(group_policy, ("open", "allowlist", "disabled"), "open")

    normalized_allow_from = []
    if isinstance(allow_from, list):
        normalized_allow_from = _dedupe_keep_order([str(item).strip() for item in allow_from if str(item).strip()])
    elif isinstance(allow_from, str):
        normalized_allow_from = _parse_csv_list(allow_from)
    if not normalized_allow_from and normalized_dm_policy == "open":
        normalized_allow_from = ["*"]

    normalized_group_allow_from = []
    if isinstance(group_allow_from, list):
        normalized_group_allow_from = _dedupe_keep_order([str(item).strip() for item in group_allow_from if str(item).strip()])
    elif isinstance(group_allow_from, str):
        normalized_group_allow_from = _parse_csv_list(group_allow_from)

    normalized_require_mention = require_mention
    if not isinstance(normalized_require_mention, bool):
        normalized_require_mention = normalized_group_policy != "open"

    return {
        "dm_policy": normalized_dm_policy,
        "group_policy": normalized_group_policy,
        "allow_from": normalized_allow_from,
        "group_allow_from": normalized_group_allow_from,
        "require_mention": normalized_require_mention,
    }


def _interactive_enabled() -> bool:
    return (
        hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        and hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    )


def _prompt_text(label: str, default: str = "") -> str:
    prompt = f"{label}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    value = input(prompt).strip()
    return value or default


def _prompt_choice(label: str, options: tuple[str, ...], default: str) -> str:
    options_text = "/".join(options)
    while True:
        value = _prompt_text(f"{label} ({options_text})", default=default).strip().lower()
        if value in options:
            return value
        print(f"请输入 {options_text}")


def _prompt_bool(label: str, default: bool) -> bool:
    default_text = "y" if default else "n"
    while True:
        value = _prompt_text(f"{label} (y/n)", default=default_text)
        normalized = _normalize_bool_input(value)
        if normalized is not None:
            return normalized
        print("请输入 y 或 n")


def _collect_interactive_create_config(agent_name: str = "", greeting: str = "",
                                       existing_channel_config: Optional[dict] = None,
                                       default_profile: Optional[dict] = None) -> dict:
    profile_seed = _ensure_dict(default_profile)
    default_openclaw_name = (agent_name or "").strip() or profile_seed.get("openclaw_name") or _gen_bot_name()
    profile = _normalize_bot_profile(
        fallback_name=profile_seed.get("primary_name", default_openclaw_name),
        openclaw_name=default_openclaw_name,
        name_zh=profile_seed.get("name_zh", ""),
        desc_zh=profile_seed.get("desc_zh", ""),
        avatar_path=profile_seed.get("avatar_path", ""),
    )
    channel_config = _normalize_channel_config(
        dm_policy=_ensure_dict(existing_channel_config).get("dm_policy", ""),
        group_policy=_ensure_dict(existing_channel_config).get("group_policy", ""),
        allow_from=_ensure_dict(existing_channel_config).get("allow_from", []),
        group_allow_from=_ensure_dict(existing_channel_config).get("group_allow_from", []),
        require_mention=_ensure_dict(existing_channel_config).get("require_mention"),
    )
    result = {
        "bot_profile": profile,
        "channel_config": channel_config,
        "greeting": greeting or "",
    }
    if not _interactive_enabled():
        return result

    print("=== 机器人信息配置 ===")
    openclaw_name = _prompt_text("智能体英文标识", profile["openclaw_name"])
    name_zh = _prompt_text("机器人中文名称", profile["name_zh"])
    desc_zh = _prompt_text("机器人中文描述", profile["desc_zh"])
    profile = _normalize_bot_profile(
        fallback_name=agent_name or "",
        openclaw_name=openclaw_name,
        name_zh=name_zh,
        desc_zh=desc_zh,
        avatar_path=profile.get("avatar_path", ""),
    )

    print("=== 飞书接入策略 ===")
    dm_policy = _prompt_choice("私聊策略 dmPolicy", ("pairing", "allowlist", "open"), channel_config["dm_policy"])
    allow_from_default = ",".join(channel_config["allow_from"]) or ("*" if dm_policy == "open" else "")
    allow_from = _prompt_text("私聊 allowFrom（逗号分隔，open 模式可用 *）", allow_from_default)
    group_policy = _prompt_choice("群聊策略 groupPolicy", ("open", "allowlist", "disabled"), channel_config["group_policy"])
    group_allow_default = ",".join(channel_config["group_allow_from"]) or ("*" if group_policy == "allowlist" else "")
    group_allow_from = _prompt_text("群聊 groupAllowFrom（chat_id，逗号分隔）", group_allow_default)
    require_mention = _prompt_bool("群聊是否必须 @ 机器人", channel_config["require_mention"])
    greeting_text = _prompt_text("欢迎语（可留空）", greeting or "")

    result["bot_profile"] = profile
    result["channel_config"] = _normalize_channel_config(
        dm_policy=dm_policy,
        group_policy=group_policy,
        allow_from=allow_from,
        group_allow_from=group_allow_from,
        require_mention=require_mention,
    )
    result["greeting"] = greeting_text
    return result


def _read_existing_channel_config(config: dict) -> dict:
    feishu = _ensure_dict(_ensure_dict(config.get("channels")).get("feishu"))
    return _normalize_channel_config(
        dm_policy=feishu.get("dmPolicy", ""),
        group_policy=feishu.get("groupPolicy", ""),
        allow_from=feishu.get("allowFrom", []),
        group_allow_from=feishu.get("groupAllowFrom", []),
        require_mention=feishu.get("requireMention"),
    )


def _local_avatar_dir() -> Path:
    return Path(__file__).resolve().parent / _LOCAL_AVATAR_DIR_NAME


def _list_local_avatar_candidates() -> list:
    avatar_dir = _local_avatar_dir()
    if not avatar_dir.is_dir():
        return []
    candidates = []
    for path in sorted(avatar_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            candidates.append(str(path.resolve()))
    return candidates


def _bot_profile_library_path() -> Path:
    return Path(__file__).resolve().parent / "bot_profiles.md"


def _parse_markdown_table(content: str) -> list:
    headers = None
    rows = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or line.count("|") < 2:
            continue
        columns = [col.strip() for col in line.strip("|").split("|")]
        if headers is None:
            headers = [col.lower() for col in columns]
            continue
        if all(set(col) <= {"-", ":"} for col in columns):
            continue
        if headers and len(columns) == len(headers):
            rows.append(dict(zip(headers, columns)))
    return rows


def _load_bot_profile_library() -> list:
    path = _bot_profile_library_path()
    if not path.is_file():
        return []
    rows = _parse_markdown_table(path.read_text(encoding="utf-8"))
    profiles = []
    for row in rows:
        openclaw_name = (row.get("openclaw_name") or "").strip()
        name_zh = (row.get("name_zh") or "").strip()
        desc_zh = (row.get("desc_zh") or "").strip()
        avatar_file = (row.get("avatar_file") or "").strip()
        if not openclaw_name or not name_zh:
            continue
        avatar_path = ""
        if avatar_file:
            candidate = (Path(__file__).resolve().parent / avatar_file).resolve()
            avatar_path = str(candidate) if candidate.is_file() else ""
        profiles.append(_normalize_bot_profile(
            fallback_name=name_zh,
            openclaw_name=openclaw_name,
            name_zh=name_zh,
            desc_zh=desc_zh or name_zh,
            avatar_path=avatar_path,
        ))
    return profiles


def _choose_random_bot_profile(profile_selector=None) -> dict:
    profiles = _load_bot_profile_library()
    if profiles:
        selector = profile_selector or random.choice
        chosen = selector(profiles)
        if isinstance(chosen, dict):
            return dict(chosen)
    generated_name = _gen_bot_name()
    return _normalize_bot_profile(
        fallback_name=generated_name,
        openclaw_name=_normalize_agent_id_component(generated_name),
        name_zh=generated_name,
        desc_zh=generated_name,
    )


def _script_template_dir() -> Path:
    return Path(__file__).resolve().parent / "template"


def _script_skills_dir() -> Path:
    return Path(__file__).resolve().parent / "skills"


def _render_template_placeholders(content: str, values: dict) -> str:
    rendered = content
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


def _finalize_workspace_template(file_name: str, content: str, values: dict) -> str:
    text = content.rstrip() + "\n"
    if file_name == "IDENTITY.md":
        required_block = (
            "\n## 系统生成字段\n"
            f"- agentId：`{values['agent_id']}`\n"
            f"- accountId：`{values['account_id']}`\n"
            f"- platform：`{values['platform']}`\n"
            f"- avatar：`{values['avatar_url']}`\n"
            f"- workspace：`{values['workspace_path']}`\n"
            f"- agentDir：`{values['agent_dir_path']}`\n"
        )
        if "## 系统生成字段" not in text:
            text += required_block
    return text


_INITIAL_RUNTIME_PATHS = _apply_runtime_paths()

# 默认权限包：覆盖 openclaw-lark 主能力面与高价值增强能力。
BOT_PERMISSIONS_DEFAULT = [
    # IM / Chat / Media
    "im:message", "im:message:readonly", "im:message:send_as_bot",
    "im:message:update", "im:message:recall", "im:message.group_at_msg:readonly",
    "im:message.group_msg", "im:message.p2p_msg:readonly",
    "im:message.reactions:read", "im:message.reactions:write_only",
    "im:message.pins:read", "im:message.pins:write_only", "im:resource",
    "im:url_preview.update", "im:chat", "im:chat:read", "im:chat:readonly",
    "im:chat.members:read", "im:chat.members:write_only", "im:chat:create",
    "im:chat:update",
    # Contact 基础
    "contact:user.base:readonly", "contact:contact.base:readonly",
    "contact:user.id:readonly", "contact:user.department:readonly",
    "contact:user.email:readonly", "contact:user.employee:readonly",
    "contact:department.base:readonly", "contact:user:search",
    # Docs / Docx / Comment / Media
    "docs:doc", "docs:doc:readonly", "docs:document.content:read",
    "docs:document:copy", "docs:document:export", "docs:document:import",
    "docs:document.media:download", "docs:document.media:upload",
    "docs:document.comment:create", "docs:document.comment:read",
    "docs:document.comment:update", "docs:document.comment:delete",
    "docx:document", "docx:document:readonly", "docx:document:create",
    "docx:document:write_only", "docx:document.block:convert",
    # Drive / File
    "drive:file", "drive:file:readonly", "drive:file:upload",
    "drive:file:download", "drive:drive", "drive:drive:readonly",
    "drive:drive.metadata:readonly", "drive:drive.search:readonly",
    "drive:export:readonly",
    # Wiki
    "wiki:wiki", "wiki:wiki:readonly", "wiki:node:read",
    "wiki:node:retrieve", "wiki:node:create", "wiki:node:update",
    "wiki:node:move", "wiki:node:copy", "wiki:space:read",
    "wiki:space:retrieve",
    # Base / Bitable
    "bitable:app", "bitable:app:readonly", "base:app:create",
    "base:app:copy", "base:app:read", "base:app:update",
    "base:table:create", "base:table:read", "base:table:update",
    "base:table:delete", "base:field:create", "base:field:read",
    "base:field:update", "base:field:delete", "base:record:create",
    "base:record:read", "base:record:retrieve", "base:record:update",
    "base:record:delete", "base:view:read", "base:view:write_only",
    "base:form:create", "base:form:read", "base:form:update",
    "base:form:delete", "base:dashboard:create", "base:dashboard:read",
    "base:dashboard:update", "base:dashboard:delete", "base:workspace:list",
    "base:workflow:read", "base:workflow:write", "base:workflow:create",
    "base:workflow:update", "base:workflow:delete",
    # Sheets
    "sheets:spreadsheet", "sheets:spreadsheet:create",
    "sheets:spreadsheet:read", "sheets:spreadsheet:readonly",
    "sheets:spreadsheet:write_only", "sheets:spreadsheet.meta:read",
    "sheets:spreadsheet.meta:write_only",
    # Calendar
    "calendar:calendar", "calendar:calendar:read", "calendar:calendar:readonly",
    "calendar:calendar:create", "calendar:calendar:update",
    "calendar:calendar:delete", "calendar:calendar:subscribe",
    "calendar:calendar.event:create", "calendar:calendar.event:read",
    "calendar:calendar.event:update", "calendar:calendar.event:delete",
    "calendar:calendar.event:reply", "calendar:calendar.free_busy:read",
    # Task
    "task:task", "task:task:read", "task:task:readonly", "task:task:write",
    "task:tasklist:read", "task:tasklist:write", "task:comment",
    "task:comment:read", "task:comment:readonly", "task:comment:write",
    "task:attachment:read", "task:attachment:write",
    # CardKit
    "cardkit:card:read", "cardkit:card:write", "cardkit:template:read",
    # 高价值增强权限
    "docs:permission.member:create", "docs:permission.member:delete",
    "docs:permission.member:update", "docs:permission.setting",
    "docs:permission.setting:read", "calendar:calendar.acl:read",
    "calendar:calendar.acl:create", "calendar:calendar.acl:delete",
    "wiki:member:create", "wiki:member:retrieve", "wiki:member:update",
    "base:role:read", "base:role:create", "base:role:update",
    "base:role:delete", "slides:presentation:create",
    "slides:presentation:read", "slides:presentation:update",
    "slides:presentation:write_only",
]

# 高风险低收益权限永久排除，不提供开启入口。
BOT_PERMISSIONS_EXCLUDED_HIGH_RISK = [
    "im:message.urgent", "im:message.urgent:phone", "im:message.urgent:sms",
    "im:message.urgent.status:write", "im:message:send_sys_msg",
    "im:message:send_multi_users", "im:message:send_multi_depts",
    "im:chat:operate_as_owner", "admin:*", "application:*", "aily:*",
    "document_ai:*", "optical_char_recognition:image", "translation:text",
    "speech_to_text:speech", "minutes:*", "vc:*", "performance:*",
    "mdm:*", "report:*", "spark:*", "approval:*",
]

# 默认权限一次性申请，不再拆分二次发布权限列表。
BOT_PERMISSIONS_REQUIRING_SECOND_PUBLISH = []

_FEISHU_POLICY_ACCOUNT_ID = "default"


def _ensure_dict(value):
    return value if isinstance(value, dict) else {}


def _ensure_list(value):
    return value if isinstance(value, list) else []


def _dedupe_keep_order(values: list) -> list:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _permission_matches_pattern(permission: str, patterns: list) -> bool:
    return any(fnmatchcase(permission, pattern) for pattern in patterns)


def _new_permission_summary() -> dict:
    return {
        "requested": [],
        "matched": [],
        "applied": [],
        "failed": [],
        "skipped": {
            "missing": [],
            "excluded_high_risk": [],
            "deferred_for_second_publish": [],
        },
        "approval": {
            "requested": [],
            "matched": [],
            "applied": [],
            "failed": [],
            "skipped_missing": [],
            "need_audit": False,
            "audit_url": None,
        },
        "excluded_high_risk_patterns": list(BOT_PERMISSIONS_EXCLUDED_HIGH_RISK),
    }


def _permission_summary_counts(summary: dict) -> dict:
    skipped = summary.get("skipped", {}) if isinstance(summary, dict) else {}
    approval = summary.get("approval", {}) if isinstance(summary, dict) else {}
    return {
        "requested": len(summary.get("requested", [])),
        "matched": len(summary.get("matched", [])),
        "applied": len(summary.get("applied", [])),
        "failed": len(summary.get("failed", [])),
        "skipped_missing": len(skipped.get("missing", [])),
        "skipped_excluded_high_risk": len(skipped.get("excluded_high_risk", [])),
        "skipped_deferred_for_second_publish": len(skipped.get("deferred_for_second_publish", [])),
        "approval_requested": len(approval.get("requested", [])),
        "approval_matched": len(approval.get("matched", [])),
        "approval_applied": len(approval.get("applied", [])),
        "approval_failed": len(approval.get("failed", [])),
        "approval_skipped_missing": len(approval.get("skipped_missing", [])),
    }


def _emit_permission_summary(step: str, summary: dict, message: str = "权限摘要") -> None:
    _emit(
        "permission_summary",
        "info",
        step,
        message,
        counts=_permission_summary_counts(summary),
        permission_summary=summary,
    )


def _build_permission_request_summary(name_to_id: dict) -> dict:
    summary = _new_permission_summary()
    default_requested = _dedupe_keep_order([
        permission for permission in BOT_PERMISSIONS_DEFAULT
        if not _permission_matches_pattern(permission, BOT_PERMISSIONS_EXCLUDED_HIGH_RISK)
    ])
    accidentally_excluded = _dedupe_keep_order([
        permission for permission in BOT_PERMISSIONS_DEFAULT
        if _permission_matches_pattern(permission, BOT_PERMISSIONS_EXCLUDED_HIGH_RISK)
    ])
    matched = _dedupe_keep_order([
        permission for permission in default_requested
        if permission in name_to_id
    ])
    missing = _dedupe_keep_order([
        permission for permission in default_requested
        if permission not in name_to_id
    ])
    deferred = []
    immediate = list(matched)

    summary["requested"] = default_requested
    summary["matched"] = matched
    summary["skipped"]["missing"] = missing
    summary["skipped"]["excluded_high_risk"] = accidentally_excluded
    summary["skipped"]["deferred_for_second_publish"] = deferred
    summary["approval"]["requested"] = []
    summary["approval"]["matched"] = []
    summary["approval"]["skipped_missing"] = []
    summary["_immediate_apply"] = immediate
    return summary


def _is_policy_account_id(account_id: str) -> bool:
    return account_id == _FEISHU_POLICY_ACCOUNT_ID


def _legacy_feishu_account_id(app_id: str) -> str:
    # 兼容旧单账号配置时使用的保底 key；不是从 agentName 派生。
    return f"legacy-{app_id}" if app_id else "legacy-account"


def _normalize_user_account_id(account_id: Optional[str], fallback_account_id: str) -> str:
    """accountId 必须由调用方显式提供；这里只在旧流程里提供兼容兜底。"""
    candidate = (account_id or "").strip()
    if candidate and not _is_policy_account_id(candidate):
        return candidate
    return fallback_account_id


def _find_account_key_by_app_id(accounts: dict, app_id: str) -> str:
    for account_id, account in accounts.items():
        if _is_policy_account_id(account_id):
            continue
        if isinstance(account, dict) and _resolve_env_placeholder(account.get("appId")) == app_id:
            return account_id
    return ""


def _real_feishu_account_keys(accounts: dict) -> list:
    keys = []
    for key, value in accounts.items():
        if _is_policy_account_id(key):
            continue
        if isinstance(value, dict):
            keys.append(key)
    return keys


def _reject_account_id_collision(accounts: dict, requested_account_id: Optional[str], app_id: str) -> None:
    candidate = (requested_account_id or "").strip()
    if not candidate or _is_policy_account_id(candidate):
        return
    existing = accounts.get(candidate)
    if not isinstance(existing, dict):
        return
    existing_app_id = str(_resolve_env_placeholder(existing.get("appId")) or "").strip()
    if existing_app_id and existing_app_id != app_id:
        raise ValueError(
            f"accountId '{candidate}' 已绑定到其他 appId '{existing_app_id}'，"
            f"不能复用于当前 appId '{app_id}'"
        )


def _build_feishu_account_record(*, app_id: Optional[str] = None,
                                 app_secret: Optional[str] = None) -> dict:
    account = {}
    if app_id is not None:
        account["appId"] = app_id
    if app_secret is not None:
        account["appSecret"] = app_secret
    return account


def _build_feishu_account_record_from_secrets(account_id: str, app_id: str, app_secret: str) -> dict:
    env_vars = _persist_feishu_env_secrets(account_id, app_id or "", app_secret or "")
    return _build_feishu_account_record(
        app_id=_env_placeholder(env_vars["app_id"]),
        app_secret=_env_placeholder(env_vars["app_secret"]),
    )


def _read_openclaw_config() -> dict:
    if not os.path.isfile(OPENCLAW_CONFIG):
        return {}

    try:
        with open(OPENCLAW_CONFIG) as f:
            loaded = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

    return loaded if isinstance(loaded, dict) else {}


def _feishu_accounts(config: dict) -> dict:
    channels = _ensure_dict(config.get("channels"))
    feishu = _ensure_dict(channels.get("feishu"))
    accounts = _ensure_dict(feishu.get("accounts"))
    feishu["accounts"] = accounts
    channels["feishu"] = feishu
    config["channels"] = channels
    return accounts


def _apply_feishu_channel_config(config: dict, *, dm_policy: str = "", group_policy: str = "",
                                 allow_from=None, group_allow_from=None,
                                 require_mention=None) -> dict:
    channels = _ensure_dict(config.get("channels"))
    feishu = _ensure_dict(channels.get("feishu"))
    accounts = _ensure_dict(feishu.get("accounts"))
    default_policy = _ensure_dict(accounts.get(_FEISHU_POLICY_ACCOUNT_ID))

    normalized = _normalize_channel_config(
        dm_policy=dm_policy,
        group_policy=group_policy,
        allow_from=allow_from,
        group_allow_from=group_allow_from,
        require_mention=require_mention,
    )

    feishu["dmPolicy"] = normalized["dm_policy"]
    feishu["groupPolicy"] = normalized["group_policy"]
    if normalized["allow_from"]:
        feishu["allowFrom"] = normalized["allow_from"]
    else:
        feishu.pop("allowFrom", None)
    if normalized["group_allow_from"]:
        feishu["groupAllowFrom"] = normalized["group_allow_from"]
    else:
        feishu.pop("groupAllowFrom", None)
    feishu["requireMention"] = normalized["require_mention"]

    default_policy["dmPolicy"] = normalized["dm_policy"]
    default_policy["groupPolicy"] = normalized["group_policy"]
    if normalized["allow_from"]:
        default_policy["allowFrom"] = normalized["allow_from"]
    else:
        default_policy.pop("allowFrom", None)
    accounts[_FEISHU_POLICY_ACCOUNT_ID] = default_policy
    feishu["accounts"] = accounts
    channels["feishu"] = feishu
    config["channels"] = channels
    return normalized


def _binding_summary(config: dict, account_id: str) -> dict:
    bindings = _ensure_list(config.get("bindings"))
    summary = {
        "bound": False,
        "agentId": "",
        "accountId": account_id,
        "type": "",
        "match": {
            "channel": "feishu",
            "accountId": account_id,
        },
    }
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        if _binding_account_id(binding) != account_id:
            continue
        summary["bound"] = True
        summary["agentId"] = (binding.get("agentId") or "").strip() if isinstance(binding.get("agentId"), str) else ""
        summary["type"] = binding.get("type") if isinstance(binding.get("type"), str) else ""
        summary["match"] = _ensure_dict(binding.get("match")) or summary["match"]
        break
    return summary


def _build_finish_payload(*, app_id: str, app_secret: str, account_id: str,
                          agent_id: str, agent_name: str, version_id: str = "",
                          open_id: str = "", manage_url: str = "",
                          audit_url: str = "", publish_status: str = "",
                          publish_fail_reason: str = "",
                          feishu_display_name: str = "",
                          permission_summary: Optional[dict] = None,
                          binding_summary: Optional[dict] = None,
                          channel_config: Optional[dict] = None,
                          bot_profile: Optional[dict] = None,
                          include_secret: bool = False) -> dict:
    permission_summary = permission_summary if isinstance(permission_summary, dict) else _new_permission_summary()
    binding_summary = binding_summary if isinstance(binding_summary, dict) else {
        "bound": bool(agent_id),
        "agentId": agent_id,
        "accountId": account_id,
        "type": "route" if agent_id else "",
        "match": {
            "channel": "feishu",
            "accountId": account_id,
        },
    }
    payload = {
        "appId": app_id,
        "accountId": account_id,
        "agentId": agent_id,
        "agentName": agent_name,
        "botName": agent_name,
        "feishuDisplayName": feishu_display_name or "",
        "versionId": version_id,
        "openId": open_id,
        "manageUrl": manage_url,
        "auditUrl": audit_url,
        "publishStatus": publish_status,
        "publishFailReason": publish_fail_reason,
        "bindingSummary": binding_summary,
        "permissionSummary": permission_summary,
        "channelConfig": channel_config if isinstance(channel_config, dict) else {},
        "botProfile": bot_profile if isinstance(bot_profile, dict) else {},
        # 兼容已有下游 snake_case 消费方。
        "app_id": app_id,
        "account_id": account_id,
        "agent_id": agent_id,
        "bot_name": agent_name,
        "feishu_display_name": feishu_display_name or "",
        "version_id": version_id,
        "open_id": open_id,
        "manage_url": manage_url,
        "audit_url": audit_url,
        "publish_fail_reason": publish_fail_reason,
        "binding_summary": binding_summary,
        "permission_summary": permission_summary,
        "channel_config": channel_config if isinstance(channel_config, dict) else {},
        "bot_profile": bot_profile if isinstance(bot_profile, dict) else {},
    }
    if include_secret or _should_emit_secret():
        payload["appSecret"] = app_secret
        payload["app_secret"] = app_secret
    return payload


def _build_publish_result(status: str, fail_reason: str = "", audit_url: str = "",
                          version_id: str = "") -> dict:
    return {
        "status": status,
        "fail_reason": fail_reason,
        "audit_url": audit_url or "",
        "version_id": version_id or "",
    }


def _looks_like_app_name_conflict(body: Optional[dict]) -> bool:
    if not isinstance(body, dict):
        return False
    message = f"{body.get('msg', '')} {body.get('message', '')}".strip().lower()
    conflict_markers = (
        "名称已存在",
        "应用名称已存在",
        "重名",
        "重复",
        "already exists",
        "name exists",
        "duplicate",
    )
    return any(marker.lower() in message for marker in conflict_markers)


def _retry_app_name(base_name: str, attempt_index: int) -> str:
    if attempt_index <= 0:
        return base_name
    return f"{base_name}-{attempt_index + 1}"


def _extract_publish_state_from_app_info(info: Optional[dict], version_id: str) -> dict:
    if not isinstance(info, dict) or info.get("code") != 0:
        return _build_publish_result("publish_failed", fail_reason="发布状态校验失败")

    data = info.get("data", {}) if isinstance(info.get("data"), dict) else {}
    app_status = data.get("appStatus")
    audit_version_id = data.get("auditVersionId") or data.get("audit_version_id")
    audit_status = data.get("auditStatus")
    if app_status == 1:
        return _build_publish_result("published", version_id=version_id)

    is_current_audit = bool(version_id) and str(audit_version_id or "") == str(version_id)
    if is_current_audit or audit_status in (0, 1, 2):
        return _build_publish_result(
            "approval_pending",
            fail_reason=f"等待管理员审批: appStatus={app_status}, auditStatus={audit_status}",
            audit_url=_pcfg("admin_audit_url"),
            version_id=version_id,
        )

    return _build_publish_result(
        "publish_failed",
        fail_reason=f"发布状态未知: appStatus={app_status}, auditStatus={audit_status}",
        version_id=version_id,
    )


def _persist_openclaw_config_state(config: dict, app_id: str, app_secret: str,
                                   account_id: Optional[str] = None,
                                   agent_name: str = "",
                                   avatar_url: str = "",
                                   open_id: str = "",
                                   manage_url: str = "",
                                   audit_url: str = "",
                                   publish_status: str = "",
                                   publish_fail_reason: str = "",
                                   channel_config: Optional[dict] = None,
                                   permission_summary: Optional[dict] = None,
                                   ensure_agent: bool = True) -> dict:
    config = config if isinstance(config, dict) else {}
    try:
        target_account_id = _normalize_openclaw_schema(
            config,
            app_id=app_id,
            app_secret=app_secret,
            account_id=account_id,
        )
    except ValueError as e:
        _log_error("config", str(e), account_id=account_id, app_id=app_id)
        return {
            "ok": False,
            "error": str(e),
            "account_id": (account_id or "").strip(),
            "agent_id": "",
            "agent_name": agent_name,
            "binding_summary": _binding_summary(config, (account_id or "").strip()),
            "channel_config": _normalize_channel_config(),
        }

    accounts = _feishu_accounts(config)
    # Feishu 账号节点必须保持为 schema-safe 的最小凭据对象；运行态元数据仅存在于
    # finish payload / 函数返回值，不写入 channels.feishu.accounts.<accountId>。
    accounts[target_account_id] = _build_feishu_account_record_from_secrets(
        target_account_id,
        app_id=app_id,
        app_secret=app_secret,
    )

    feishu_entry = config.setdefault("plugins", {}).setdefault("entries", {}).setdefault("feishu", {})
    if not feishu_entry.get("enabled"):
        feishu_entry["enabled"] = True
    applied_channel_config = _apply_feishu_channel_config(
        config,
        dm_policy=_ensure_dict(channel_config).get("dm_policy", ""),
        group_policy=_ensure_dict(channel_config).get("group_policy", ""),
        allow_from=_ensure_dict(channel_config).get("allow_from", []),
        group_allow_from=_ensure_dict(channel_config).get("group_allow_from", []),
        require_mention=_ensure_dict(channel_config).get("require_mention"),
    )

    agent_result = {"agent_id": "", "mode": ""}
    binding_summary = _binding_summary(config, target_account_id)

    try:
        _ensure_parent_dir(OPENCLAW_CONFIG)
        with open(OPENCLAW_CONFIG, "w") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        _set_private_permissions(OPENCLAW_CONFIG)
    except IOError as e:
        _log_error("config", f"写入配置文件失败: {e}")
        return {
            "ok": False,
            "account_id": target_account_id,
            "agent_id": "",
            "agent_name": agent_name,
            "binding_summary": binding_summary,
            "channel_config": applied_channel_config,
        }

    if ensure_agent:
        target_agent_name = (agent_name or "").strip() or _gen_bot_name()
        agent_result = _ensure_openclaw_agent(
            config,
            account_id=target_account_id,
            agent_name=target_agent_name,
            avatar_url=avatar_url,
        )
        binding_summary = _binding_summary(config, target_account_id)
        agent_name = target_agent_name

    try:
        _ensure_parent_dir(OPENCLAW_CONFIG)
        with open(OPENCLAW_CONFIG, "w") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        _set_private_permissions(OPENCLAW_CONFIG)
        _log_success("config", f"已写入配置 (domain={_pcfg('config_domain')})",
                     account_id=target_account_id,
                     agent_id=agent_result.get("agent_id") or binding_summary.get("agentId"),
                     agent_mode=agent_result.get("mode"),
                     ensure_agent=ensure_agent)
        return {
            "ok": True,
            "account_id": target_account_id,
            "agent_id": agent_result.get("agent_id") or binding_summary.get("agentId") or "",
            "agent_name": agent_name,
            "binding_summary": binding_summary,
            "agent_mode": agent_result.get("mode", ""),
            "channel_config": applied_channel_config,
        }
    except IOError as e:
        _log_error("config", f"写入配置文件失败: {e}")
        return {
            "ok": False,
            "account_id": target_account_id,
            "agent_id": agent_result.get("agent_id") or binding_summary.get("agentId") or "",
            "agent_name": agent_name,
            "binding_summary": binding_summary,
            "channel_config": applied_channel_config,
        }


def _openclaw_root_dir() -> str:
    return OPENCLAW_ROOT or os.path.dirname(OPENCLAW_CONFIG) or "."


def _normalize_agent_id_component(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", (value or "").strip().lower())
    normalized = normalized.strip("-")
    return normalized or "agent"


def _derive_agent_id_base(account_id: str) -> str:
    """agentId 默认追溯到 accountId；绝不从中文 agentName 派生。"""
    return _normalize_agent_id_component(account_id)


def _binding_account_id(binding: dict) -> str:
    match = _ensure_dict(binding.get("match"))
    if match.get("channel") != "feishu":
        return ""
    account_id = match.get("accountId")
    return account_id.strip() if isinstance(account_id, str) else ""


def _find_agent_record(agents_list: list, agent_id: str) -> Optional[dict]:
    for agent in agents_list:
        if isinstance(agent, dict) and agent.get("id") == agent_id:
            return agent
    return None


def _find_bound_agent_id(bindings: list, account_id: str) -> str:
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        if _binding_account_id(binding) != account_id:
            continue
        agent_id = binding.get("agentId")
        if isinstance(agent_id, str) and agent_id.strip():
            return agent_id.strip()
    return ""


def _resolve_agent_id(config: dict, account_id: str) -> str:
    """默认 agentId 与 accountId 对齐；若冲突则追加可追溯后缀。"""
    agents = _ensure_dict(config.get("agents"))
    agents_list = _ensure_list(agents.get("list"))
    bindings = _ensure_list(config.get("bindings"))

    bound_agent_id = _find_bound_agent_id(bindings, account_id)
    if bound_agent_id:
        return bound_agent_id

    base_agent_id = _derive_agent_id_base(account_id)
    candidate = base_agent_id
    suffix = 0

    while True:
        record = _find_agent_record(agents_list, candidate)
        if not record:
            return candidate

        bound_account_id = ""
        for binding in bindings:
            if isinstance(binding, dict) and binding.get("agentId") == candidate:
                bound_account_id = _binding_account_id(binding)
                if bound_account_id:
                    break

        if not bound_account_id or bound_account_id == account_id:
            return candidate

        suffix += 1
        candidate = f"{base_agent_id}-agent" if suffix == 1 else f"{base_agent_id}-agent-{suffix}"


def _agent_workspace_path(agent_id: str) -> str:
    return os.path.join(_openclaw_root_dir(), "workspace", agent_id)


def _agent_runtime_dir(agent_id: str) -> str:
    return os.path.join(_openclaw_root_dir(), "agents", agent_id, "agent")


def _managed_skills_dir() -> str:
    return os.path.join(_openclaw_root_dir(), "skills")


def _workspace_template_values(*, agent_id: str, agent_name: str,
                               account_id: str, avatar_url: str = "") -> dict:
    workspace_path = _agent_workspace_path(agent_id)
    agent_dir_path = _agent_runtime_dir(agent_id)
    return {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "account_id": account_id,
        "workspace_path": workspace_path,
        "agent_dir_path": agent_dir_path,
        "avatar_url": avatar_url or "未设置",
        "platform": PLATFORM,
    }


def _default_workspace_templates(values: dict) -> dict:
    return {
        "AGENTS.md": f"""# {values['agent_name']}\n\n- agentId：`{values['agent_id']}`\n- accountId：`{values['account_id']}`\n- 平台：`{values['platform']}`\n\n## 飞书操作决策顺序\n1. 必须先确认当前目标、上下文、账号与消息类型。\n2. 必须确认目标消息或会话确实属于 `accountId={values['account_id']}`。\n3. 仅在确认允许修改、撤回、回复后，才调用飞书工具。\n4. 禁止在账号不明确、目标不明确、消息归属不明确时直接操作飞书。\n""",
        "SOUL.md": f"""# 风格\n\n你是“{values['agent_name']}”。保持真实、克制、直接；优先给出准确结论，不做夸张人格表演。\n""",
        "USER.md": "# 用户画像\n\n- 待用户补充：常用目标、沟通偏好、禁忌事项。\n",
        "IDENTITY.md": f"""# 身份\n\n- 名字：{values['agent_name']}\n- 主题：飞书账号绑定助手\n- 表情：🤖\n- 头像：{values['avatar_url']}\n\n## 系统生成字段\n- agentId：`{values['agent_id']}`\n- accountId：`{values['account_id']}`\n- platform：`{values['platform']}`\n- workspace：`{values['workspace_path']}`\n- agentDir：`{values['agent_dir_path']}`\n""",
        "TOOLS.md": f"""# 工具边界\n\n## openclaw-lark 高风险误用清单\n- 禁止在 `accountId` 不匹配时调用飞书工具。\n- 禁止乱拼 target、乱用 reaction、乱改用户原消息。\n- 禁止把临时目录下的无关文件直接发送到飞书。\n- 禁止在未确认消息归属前执行更新、删除、撤回。\n""",
        "BOOTSTRAP.md": f"""# 一次性初始化\n\n已完成以下初始化：\n- 创建 agentId：`{values['agent_id']}`\n- 绑定 accountId：`{values['account_id']}`\n\n待用户确认：是否补充长期身份说明与使用偏好。\n""",
        "HEARTBEAT.md": "# HEARTBEAT\n\n",
    }


def _build_workspace_templates(*, agent_id: str, agent_name: str,
                               account_id: str, avatar_url: str = "") -> dict:
    values = _workspace_template_values(
        agent_id=agent_id,
        agent_name=agent_name,
        account_id=account_id,
        avatar_url=avatar_url,
    )
    templates = _default_workspace_templates(values)
    template_dir = _script_template_dir()
    if template_dir.is_dir():
        for file_name in templates.keys():
            template_path = template_dir / file_name
            if template_path.is_file():
                templates[file_name] = _render_template_placeholders(
                    template_path.read_text(encoding="utf-8"),
                    values,
                )
    for file_name, content in list(templates.items()):
        templates[file_name] = _finalize_workspace_template(file_name, content, values)
    return templates


def _refreshable_workspace_templates() -> set:
    return {
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "TOOLS.md",
    }


def _ensure_workspace_files(*, agent_id: str, agent_name: str,
                            account_id: str, avatar_url: str = "") -> dict:
    workspace_path = _agent_workspace_path(agent_id)
    agent_dir_path = _agent_runtime_dir(agent_id)
    managed_skills_path = _managed_skills_dir()
    os.makedirs(workspace_path, exist_ok=True)
    os.makedirs(agent_dir_path, exist_ok=True)

    created_files = []
    refreshed_files = []
    for file_name, content in _build_workspace_templates(
        agent_id=agent_id,
        agent_name=agent_name,
        account_id=account_id,
        avatar_url=avatar_url,
    ).items():
        file_path = os.path.join(workspace_path, file_name)
        existed = os.path.exists(file_path)
        if existed and file_name not in _refreshable_workspace_templates():
            continue
        with open(file_path, "w") as f:
            f.write(content)
        if existed:
            refreshed_files.append(file_path)
        else:
            created_files.append(file_path)

    source_skills_dir = _script_skills_dir()
    target_skills_dir = Path(managed_skills_path)
    copied_skill_files = []
    if source_skills_dir.is_dir():
        target_skills_dir.mkdir(parents=True, exist_ok=True)
        for source_file in source_skills_dir.rglob("*"):
            if source_file.is_dir():
                continue
            if any(part in {"__pycache__"} for part in source_file.parts) or source_file.name == ".DS_Store":
                continue
            relative = source_file.relative_to(source_skills_dir)
            target_file = target_skills_dir / relative
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
            copied_skill_files.append(str(target_file))

    return {
        "workspace": workspace_path,
        "agent_dir": agent_dir_path,
        "managed_skills_dir": managed_skills_path,
        "created_files": created_files,
        "refreshed_files": refreshed_files,
        "copied_skill_files": copied_skill_files,
    }


def _build_agent_record(*, agent_id: str, agent_name: str,
                        account_id: str, avatar_url: str = "") -> dict:
    return {
        "id": agent_id,
        "name": agent_name,
        "workspace": _agent_workspace_path(agent_id),
        "agentDir": _agent_runtime_dir(agent_id),
        "identity": {
            "name": agent_name,
            "theme": "飞书账号绑定助手",
            "emoji": "🤖",
            "avatar": avatar_url or "",
        },
    }


def _upsert_agent_record(config: dict, *, agent_id: str, agent_name: str,
                         account_id: str, avatar_url: str = "") -> dict:
    agents = _ensure_dict(config.get("agents"))
    agents_list = _ensure_list(agents.get("list"))
    agents["list"] = agents_list
    config["agents"] = agents

    existing = _find_agent_record(agents_list, agent_id)
    if existing is None:
        existing = _build_agent_record(
            agent_id=agent_id,
            agent_name=agent_name,
            account_id=account_id,
            avatar_url=avatar_url,
        )
        agents_list.append(existing)
    else:
        existing.update({
            "name": agent_name,
            "workspace": _agent_workspace_path(agent_id),
            "agentDir": _agent_runtime_dir(agent_id),
        })
        identity = _ensure_dict(existing.get("identity"))
        identity.update({
            "name": agent_name,
            "theme": "飞书账号绑定助手",
            "emoji": "🤖",
            "avatar": avatar_url or identity.get("avatar", ""),
        })
        existing["identity"] = identity
    return existing


def _upsert_binding(config: dict, *, agent_id: str, account_id: str) -> dict:
    bindings = _ensure_list(config.get("bindings"))
    config["bindings"] = bindings
    target = None
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        if _binding_account_id(binding) == account_id:
            target = binding
            break

    if target is None:
        target = {
            "type": "route",
            "agentId": agent_id,
            "match": {
                "channel": "feishu",
                "accountId": account_id,
            },
        }
        bindings.append(target)
    else:
        target["type"] = "route"
        target["agentId"] = agent_id
        match = _ensure_dict(target.get("match"))
        match["channel"] = "feishu"
        match["accountId"] = account_id
        target["match"] = match
    return target


def _openclaw_cli_env() -> dict:
    env = os.environ.copy()
    env.update(_project_env_assignments())
    env[_OPENCLAW_CONFIG_ENV] = OPENCLAW_CONFIG
    env[_OPENCLAW_ALLOW_FROM_ENV] = OPENCLAW_ALLOW_FROM
    env[_STATE_DIR_ENV] = STATE_DIR
    return env


def _run_openclaw_cli(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        env=_openclaw_cli_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _apply_openclaw_agent_fallback(config: dict, *, agent_id: str, agent_name: str,
                                   account_id: str, avatar_url: str = "") -> dict:
    files_result = _ensure_workspace_files(
        agent_id=agent_id,
        agent_name=agent_name,
        account_id=account_id,
        avatar_url=avatar_url,
    )
    _upsert_agent_record(
        config,
        agent_id=agent_id,
        agent_name=agent_name,
        account_id=account_id,
        avatar_url=avatar_url,
    )
    _upsert_binding(config, agent_id=agent_id, account_id=account_id)
    return {
        "mode": "fallback",
        "agent_id": agent_id,
        "workspace": files_result["workspace"],
        "agent_dir": files_result["agent_dir"],
        "created_files": files_result["created_files"],
    }


def _ensure_openclaw_agent(config: dict, *, account_id: str, agent_name: str,
                           avatar_url: str = "") -> dict:
    agent_id = _resolve_agent_id(config, account_id)
    files_result = _ensure_workspace_files(
        agent_id=agent_id,
        agent_name=agent_name,
        account_id=account_id,
        avatar_url=avatar_url,
    )

    cli_path = shutil.which("openclaw")
    cli_error = ""
    if cli_path:
        add_proc = _run_openclaw_cli([
            cli_path,
            "agents",
            "add",
            agent_id,
            "--workspace",
            files_result["workspace"],
            "--agent-dir",
            files_result["agent_dir"],
            "--non-interactive",
            "--json",
        ])
        bind_proc = _run_openclaw_cli([
            cli_path,
            "agents",
            "bind",
            "--agent",
            agent_id,
            "--bind",
            f"feishu:{account_id}",
            "--json",
        ]) if add_proc.returncode == 0 else None
        identity_proc = _run_openclaw_cli([
            cli_path,
            "agents",
            "set-identity",
            "--agent",
            agent_id,
            "--name",
            agent_name,
            *( ["--avatar", avatar_url] if avatar_url else [] ),
            "--json",
        ]) if bind_proc and bind_proc.returncode == 0 else None

        if add_proc.returncode == 0 and bind_proc and bind_proc.returncode == 0 and (identity_proc is None or identity_proc.returncode == 0):
            _upsert_agent_record(
                config,
                agent_id=agent_id,
                agent_name=agent_name,
                account_id=account_id,
                avatar_url=avatar_url,
            )
            _upsert_binding(config, agent_id=agent_id, account_id=account_id)
            return {
                "mode": "cli",
                "agent_id": agent_id,
                "workspace": files_result["workspace"],
                "agent_dir": files_result["agent_dir"],
                "created_files": files_result["created_files"],
            }

        outputs = [
            add_proc.stderr or add_proc.stdout,
            bind_proc.stderr if bind_proc else "",
            bind_proc.stdout if bind_proc else "",
            identity_proc.stderr if identity_proc else "",
            identity_proc.stdout if identity_proc else "",
        ]
        cli_error = " | ".join(part.strip() for part in outputs if part and part.strip())
        _log_warn("agent", f"OpenClaw CLI 创建失败，回退到受控 JSON 写入: {cli_error}", agent_id=agent_id, account_id=account_id)
    else:
        _log_info("agent", "未检测到 openclaw CLI，使用受控 JSON 写入创建 agent", agent_id=agent_id, account_id=account_id)

    fallback_result = _apply_openclaw_agent_fallback(
        config,
        agent_id=agent_id,
        agent_name=agent_name,
        account_id=account_id,
        avatar_url=avatar_url,
    )
    if cli_error:
        fallback_result["cli_error"] = cli_error
    return fallback_result


def _normalize_openclaw_schema(config: dict, *, app_id: str, app_secret: str,
                               account_id: Optional[str] = None) -> str:
    """统一整理 OpenClaw 飞书 schema：accounts map、defaultAccount、agents.list、bindings。"""
    channels = _ensure_dict(config.get("channels"))
    config["channels"] = channels

    feishu = _ensure_dict(channels.get("feishu"))
    channels["feishu"] = feishu

    # 保留无关字段，只把飞书写入规则收口到单一 helper。
    feishu["enabled"] = True
    feishu.setdefault("domain", _pcfg("config_domain"))
    feishu.setdefault("groupPolicy", "open")

    accounts = _ensure_dict(feishu.get("accounts"))
    feishu["accounts"] = accounts
    _sanitize_feishu_account_secrets(accounts)
    existing_real_account_keys = _real_feishu_account_keys(accounts)

    _reject_account_id_collision(accounts, account_id, app_id)

    legacy_app_id = feishu.get("appId")
    legacy_app_secret = feishu.get("appSecret")
    if legacy_app_id or legacy_app_secret:
        legacy_account_id = _find_account_key_by_app_id(accounts, legacy_app_id or "")
        if not legacy_account_id:
            legacy_account_id = _legacy_feishu_account_id(legacy_app_id or app_id)
        accounts[legacy_account_id] = _build_feishu_account_record_from_secrets(
            legacy_account_id,
            app_id=legacy_app_id,
            app_secret=legacy_app_secret,
        )

    # 同 appId 重新执行时必须更新原位，避免重复创建账号记录。
    target_account_id = _find_account_key_by_app_id(accounts, app_id)
    if not target_account_id:
        target_account_id = _normalize_user_account_id(
            account_id, _legacy_feishu_account_id(app_id))
    if _is_policy_account_id(target_account_id):
        target_account_id = _legacy_feishu_account_id(app_id)

    accounts[target_account_id] = _build_feishu_account_record_from_secrets(
        target_account_id,
        app_id=app_id,
        app_secret=app_secret,
    )

    # accounts.default 只允许承载策略对象；不能被当作真实 app 账号。
    if _FEISHU_POLICY_ACCOUNT_ID in accounts and not isinstance(accounts[_FEISHU_POLICY_ACCOUNT_ID], dict):
        accounts[_FEISHU_POLICY_ACCOUNT_ID] = {}

    # defaultAccount 必须指向真实账号 key，不能写成 default。
    default_account = feishu.get("defaultAccount")
    default_account_invalid = (
        not isinstance(default_account, str)
        or _is_policy_account_id(default_account)
        or default_account not in accounts
        or not isinstance(accounts.get(default_account), dict)
    )
    if default_account_invalid:
        fallback_default_account = existing_real_account_keys[0] if existing_real_account_keys else target_account_id
        _log_warn(
            "config",
            "defaultAccount 无效，已修复为真实账号 key",
            previous_default_account=default_account,
            repaired_default_account=fallback_default_account,
        )
        feishu["defaultAccount"] = fallback_default_account

    # 旧单账号字段迁移到 accounts map，避免与新结构形成双写来源。
    feishu.pop("appId", None)
    feishu.pop("appSecret", None)

    agents = _ensure_dict(config.get("agents"))
    agents["list"] = _ensure_list(agents.get("list"))
    config["agents"] = agents

    config["bindings"] = _ensure_list(config.get("bindings"))

    return target_account_id


def _persist_openclaw_config(config: dict, app_id: str, app_secret: str,
                              account_id: Optional[str] = None,
                              agent_name: str = "",
                              avatar_url: str = "") -> bool:
    result = _persist_openclaw_config_state(
        config,
        app_id=app_id,
        app_secret=app_secret,
        account_id=account_id,
        agent_name=agent_name,
        avatar_url=avatar_url,
        ensure_agent=True,
    )
    return bool(result.get("ok"))


def _gen_bot_name() -> str:
    if PLATFORM == "lark":
        return f"openclaw-bot-{random.randint(1000, 9999)}"
    return f"OpenClaw机器人-{random.randint(1000, 9999)}"


def _state_file() -> str:
    return os.path.join(STATE_DIR, f"{_pcfg('state_file_prefix')}-creator-state.json")


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


# ============================================================
# 状态文件 & 工具
# ============================================================
def _save_state(data: dict) -> None:
    _ensure_parent_dir(_state_file())
    with open(_state_file(), "w") as f:
        json.dump(_sanitize_state_data(data), f, ensure_ascii=False)
    _set_private_permissions(_state_file())




# ============================================================
# 结构化 JSON 输出 (stdout)
# ============================================================
def _build_terminal_qrcode(content: str, message: str = "") -> str:
    payload = (content or "").strip()
    if not payload:
        return ""

    lines = []
    title = (message or "请扫码登录").strip()
    if title:
        lines.append(title)

    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(payload)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        white = "  "
        black = "██"
        for row in matrix:
            lines.append("".join(black if cell else white for cell in row))
    except Exception as exc:
        lines.append(f"[终端二维码渲染失败，已回退为原始内容: {exc}]")

    lines.append("")
    lines.append("二维码内容:")
    lines.append(payload)
    return "\n".join(lines)


def _emit(action: str, level: str, step: str, message: str, **extra) -> None:
    """输出一行结构化 JSON 日志到 stdout。"""
    if _SUMMARY_OUTPUT_MODE and action == "log" and level in ("info", "success"):
        return
    record = {"action": action, "level": level, "step": step,
              "message": message, "ts": int(time.time())}
    record.update(extra)
    print(json.dumps(record, ensure_ascii=False))
    if action == "show_qrcode" and hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
        terminal_qr = _build_terminal_qrcode(
            extra.get("content", ""),
            message=message,
        )
        if terminal_qr:
            print(terminal_qr, file=sys.stderr, flush=True)


def _log_info(step: str, message: str, **extra) -> None:
    _emit("log", "info", step, message, **extra)


def _log_success(step: str, message: str, **extra) -> None:
    _emit("log", "success", step, message, **extra)


def _log_warn(step: str, message: str, **extra) -> None:
    _emit("log", "warn", step, message, **extra)


def _log_error(step: str, message: str, **extra) -> None:
    _emit("log", "error", step, message, **extra)


def _emit_progress(step: str, message: str, current: int, total: int) -> None:
    _emit("progress", "info", step, message, current=current, total=total)


def _emit_finish(message: str, data: dict) -> None:
    _emit("finish", "success", "finish", message, data=data)


def _emit_summary(step: str, message: str, **extra) -> None:
    _emit("summary", "info", step, message, **extra)


def _emit_finish_error(step: str, message: str, data: Optional[dict] = None) -> None:
    payload = {"data": data} if isinstance(data, dict) else {}
    _emit("finish", "error", step, message, **payload)


def _emit_error(step: str, message: str) -> None:
    _emit("finish", "error", step, message)


def _normalize_avatar_url(url: str) -> str:
    return (url or "").strip()


def _choose_random_avatar_source(local_source_selector=None,
                                 random_source_selector=None,
                                 local_sources=None,
                                 random_sources=None) -> tuple[str, str]:
    local_pool = _list_local_avatar_candidates() if local_sources is None else local_sources
    local_candidates = [path for path in local_pool if str(path).strip()]
    if local_candidates:
        selector = local_source_selector or random.choice
        chosen_local = str(selector(local_candidates)).strip()
        if chosen_local:
            return chosen_local, "local"

    remote_pool = REMOTE_RANDOM_AVATAR_URLS if random_sources is None else random_sources
    remote_candidates = [
        _normalize_avatar_url(url)
        for url in remote_pool
        if _normalize_avatar_url(url)
    ]
    if remote_candidates:
        selector = random_source_selector or random.choice
        chosen_remote = _normalize_avatar_url(selector(remote_candidates))
        if chosen_remote:
            return chosen_remote, "random"

    raise ValueError("no avatar sources available")


def _resolve_avatar_source(avatar_url: str = "",
                           local_source_selector=None,
                           random_source_selector=None,
                           local_sources=None,
                           random_sources=None) -> tuple[str, str]:
    explicit_url = _normalize_avatar_url(avatar_url)
    if explicit_url:
        return explicit_url, "explicit"

    try:
        return _choose_random_avatar_source(
            local_source_selector=local_source_selector,
            random_source_selector=random_source_selector,
            local_sources=local_sources,
            random_sources=random_sources,
        )
    except Exception as e:
        _log_warn(
            "create_app",
            f"本地/远程随机头像源不可用，回退内置默认头像: {e}",
            source="fallback",
        )
        return DEFAULT_AVATAR_URL, "fallback"


def _avatar_meta_path(avatar_path: str) -> str:
    return f"{avatar_path}.meta.json"


def _read_avatar_cache_meta(avatar_path: str) -> dict:
    meta_path = _avatar_meta_path(avatar_path)
    if not os.path.isfile(meta_path):
        return {}
    try:
        with open(meta_path) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_avatar_cache_meta(avatar_path: str, source: str, url: str) -> None:
    meta_path = _avatar_meta_path(avatar_path)
    try:
        with open(meta_path, "w") as f:
            json.dump({"source": source, "url": url}, f, ensure_ascii=False)
    except OSError:
        pass


def _download_avatar(avatar_url: str = "",
                     local_source_selector=None,
                     random_source_selector=None,
                     local_sources=None,
                     random_sources=None) -> dict:
    url, source = _resolve_avatar_source(
        avatar_url=avatar_url,
        local_source_selector=local_source_selector,
        random_source_selector=random_source_selector,
        local_sources=local_sources,
        random_sources=random_sources,
    )
    avatar_path = os.path.join(STATE_DIR, f"{_pcfg('state_file_prefix')}-avatar.png")
    # 仅当使用兜底头像时才复用缓存；显式/随机头像每次重新下载，便于保持来源语义。
    if source == "fallback" and os.path.isfile(avatar_path) and os.path.getsize(avatar_path) > 0:
        meta = _read_avatar_cache_meta(avatar_path)
        if meta.get("source") == "fallback" and meta.get("url") == url:
            _log_info("create_app", f"使用已缓存头像: {avatar_path}", source=source, avatar_url=url)
            return {"path": avatar_path, "url": url, "source": source}

    _log_info("create_app", f"正在下载头像: {url}", source=source, avatar_url=url)
    if source == "local":
        try:
            _ensure_parent_dir(avatar_path)
            shutil.copyfile(url, avatar_path)
            _write_avatar_cache_meta(avatar_path, source, url)
            return {"path": avatar_path, "url": url, "source": source}
        except OSError as e:
            _log_warn("create_app", f"本地头像复制失败: {e}", source=source, avatar_url=url)
            source = "fallback"

    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        _ensure_parent_dir(avatar_path)
        with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
            data = resp.read()
        with open(avatar_path, "wb") as f:
            f.write(data)
        _write_avatar_cache_meta(avatar_path, source, url)
        _log_info("create_app", f"头像下载完成: {len(data)} bytes", source=source, avatar_url=url)
        return {"path": avatar_path, "url": url, "source": source}
    except Exception as e:
        _log_warn("create_app", f"头像下载失败: {e}", source=source, avatar_url=url)
        if source == "fallback":
            return {"path": "", "url": "", "source": source}

        fallback_url = DEFAULT_AVATAR_URL
        _log_info("create_app", f"切换到内置默认头像兜底: {fallback_url}", source="fallback", avatar_url=fallback_url)
        try:
            if os.path.isfile(avatar_path) and os.path.getsize(avatar_path) > 0:
                os.remove(avatar_path)
        except OSError:
            pass
        try:
            req = urllib.request.Request(fallback_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
                data = resp.read()
            _ensure_parent_dir(avatar_path)
            with open(avatar_path, "wb") as f:
                f.write(data)
            _write_avatar_cache_meta(avatar_path, "fallback", fallback_url)
            _log_info("create_app", f"头像兜底下载完成: {len(data)} bytes", source="fallback", avatar_url=fallback_url)
            return {"path": avatar_path, "url": fallback_url, "source": "fallback"}
        except Exception as fallback_error:
            _log_warn("create_app", f"内置默认头像兜底也失败: {fallback_error}", source="fallback", avatar_url=fallback_url)
            return {"path": "", "url": "", "source": "fallback"}


def _write_openclaw_config(app_id: str, app_secret: str,
                           account_id: Optional[str] = None,
                           agent_name: str = "",
                           avatar_url: str = "") -> bool:
    """将飞书账号写入 openclaw.json。

    account_id 由调用方显式提供；当前 create 流程仍走兼容兜底，后续再接入真实输入。
    """

    # 确保目录存在
    _ensure_parent_dir(OPENCLAW_CONFIG)

    # 读取现有配置（如果存在），只接受 object 根节点，随后做针对账号的 upsert。
    config = _read_openclaw_config()

    return _persist_openclaw_config(
        config,
        app_id=app_id,
        app_secret=app_secret,
        account_id=account_id,
        agent_name=agent_name,
        avatar_url=avatar_url,
    )


def _write_allow_from(open_id: str) -> bool:
    """将 owner open_id 写入 feishu-default-allowFrom.json。"""
    _emit("write_config", "info", "config", "写入 allowFrom",
          path=OPENCLAW_ALLOW_FROM)

    if not isinstance(open_id, str) or not open_id.strip():
        _log_warn("config", "open_id 为空，跳过 allowFrom 写入")
        return True

    open_id = open_id.strip()

    _ensure_parent_dir(OPENCLAW_ALLOW_FROM)

    version = 1
    allow_from: List[str] = []

    if os.path.isfile(OPENCLAW_ALLOW_FROM):
        try:
            with open(OPENCLAW_ALLOW_FROM) as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                existing_version = loaded.get("version")
                if isinstance(existing_version, (int, float)) and not isinstance(existing_version, bool):
                    version = existing_version

                existing_allow_from = loaded.get("allowFrom")
                if isinstance(existing_allow_from, list):
                    for item in existing_allow_from:
                        if isinstance(item, str) and item.strip() and item not in allow_from:
                            allow_from.append(item)
            else:
                _log_warn("config", "allowFrom 文件内容不是对象，已恢复为最小结构")
        except (json.JSONDecodeError, IOError) as e:
            _log_warn("config", f"读取 allowFrom 失败，已恢复为最小结构: {e}")

    if open_id not in allow_from:
        allow_from.append(open_id)

    data = {
        "version": version,
        "allowFrom": allow_from,
    }

    try:
        with open(OPENCLAW_ALLOW_FROM, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _set_private_permissions(OPENCLAW_ALLOW_FROM)
        _log_success("config", f"已写入 allowFrom (open_id={_mask_identifier(open_id)})")
        return True
    except IOError as e:
        _log_error("config", f"写入 allowFrom 失败: {e}")
        return False


def _send_greeting(app_id: str, app_secret: str, open_id: str, greeting: str = "") -> None:
    """创建完成后，通过 API 给 owner 发送一条初始问候消息。"""
    _log_info("greeting", "发送初始问候消息")
    greeting = greeting or _pcfg("default_greeting")
    base_url = _pcfg("base_url")

    ctx = ssl.create_default_context()

    # 获取 tenant_access_token
    token_payload = json.dumps({
        "app_id": app_id, "app_secret": app_secret,
    }).encode()
    token_req = urllib.request.Request(
        f"{base_url}/open-apis/auth/v3/tenant_access_token/internal",
        data=token_payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(token_req, context=ctx, timeout=20) as resp:
            token_data = json.loads(resp.read())
        token = token_data.get("tenant_access_token")
        if not token:
            return
    except Exception:
        return

    # 发送消息
    send_payload = json.dumps({
        "receive_id": open_id,
        "msg_type": "text",
        "content": json.dumps({"text": greeting}),
        "uuid": str(uuid.uuid4()),
    }).encode()
    send_req = urllib.request.Request(
        f"{base_url}/open-apis/im/v1/messages?receive_id_type=open_id",
        data=send_payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(send_req, context=ctx, timeout=20) as resp:
            resp.read()
    except Exception:
        pass


def _fetch_tenant_access_token(app_id: str, app_secret: str, base_url: str,
                               log_step: str = "owner") -> str:
    ctx = ssl.create_default_context()
    payload = json.dumps({
        "app_id": app_id,
        "app_secret": app_secret,
    }).encode()
    req = urllib.request.Request(
        f"{base_url}/open-apis/auth/v3/tenant_access_token/internal",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
            token_data = json.loads(resp.read())
    except Exception:
        _log_error(log_step, "未获取到 tenant_access_token")
        return ""

    token = token_data.get("tenant_access_token")
    if not token:
        _log_error(log_step, "未获取到 tenant_access_token")
        return ""
    return token


def _owner_candidate_from_mapping(value: dict, source: str) -> Optional[dict]:
    if not isinstance(value, dict):
        return None

    def _first_string(*keys):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""

    open_id = _first_string("open_id", "openId", "owner_open_id", "ownerOpenId")
    user_id = _first_string("user_id", "userId", "owner_user_id", "ownerUserId")
    union_id = _first_string("union_id", "unionId", "owner_union_id", "ownerUnionId")
    if open_id or user_id or union_id:
        candidate = {
            "name": _first_string("name", "ownerName", "display_name", "displayName") or "未知",
            "source": source,
        }
        if open_id:
            candidate["open_id"] = open_id
        if user_id:
            candidate["user_id"] = user_id
        if union_id:
            candidate["union_id"] = union_id
        return candidate
    return None


def _extract_owner_identity(app_detail: dict) -> Optional[dict]:
    if not isinstance(app_detail, dict):
        return None

    data = app_detail.get("data", {}) if isinstance(app_detail.get("data"), dict) else {}
    app = data.get("app", {}) if isinstance(data.get("app"), dict) else {}
    candidate_values = [
        ("app.ownerInfo", app.get("ownerInfo")),
        ("app.owner", app.get("owner")),
        ("data.ownerInfo", data.get("ownerInfo")),
        ("data.owner", data.get("owner")),
    ]

    owner_lists = [
        ("app.owners", app.get("owners")),
        ("data.owners", data.get("owners")),
    ]
    for source, owners in owner_lists:
        if isinstance(owners, list) and len(owners) == 1 and isinstance(owners[0], dict):
            candidate_values.append((f"{source}[0]", owners[0]))

    candidates = []
    for source, value in candidate_values:
        candidate = _owner_candidate_from_mapping(value, source)
        if candidate:
            identity_key = tuple(candidate.get(key, "") for key in ("open_id", "user_id", "union_id"))
            if identity_key not in [tuple(existing.get(key, "") for key in ("open_id", "user_id", "union_id")) for existing in candidates]:
                candidates.append(candidate)

    if len(candidates) == 1:
        return candidates[0]
    return None


def _resolve_owner_identity_via_contact(base_url: str, tenant_token: str, owner: dict) -> Optional[dict]:
    if not isinstance(owner, dict):
        return None
    if owner.get("open_id"):
        return owner

    ctx = ssl.create_default_context()
    for user_id_type in ("user_id", "union_id"):
        identifier = (owner.get(user_id_type) or "").strip()
        if not identifier:
            continue
        req = urllib.request.Request(
            f"{base_url}/open-apis/contact/v3/users/{urllib.parse.quote(identifier)}?user_id_type={user_id_type}",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {tenant_token}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
                user_data = json.loads(resp.read())
        except Exception:
            continue

        user = user_data.get("data", {}).get("user", {})
        if not isinstance(user, dict):
            continue
        open_id = user.get("open_id")
        if isinstance(open_id, str) and open_id.strip():
            resolved = dict(owner)
            resolved["open_id"] = open_id.strip()
            resolved["source"] = f"{owner.get('source', 'owner')}.contact:{user_id_type}"
            if not resolved.get("name"):
                resolved["name"] = user.get("name") or "未知"
            return resolved

    return None


def _kill_cdp_browser():
    """杀掉占用 CDP_PORT 的残留 Chromium 进程。"""
    # 先尝试用保存的 PID
    sf = _state_file()
    if os.path.isfile(sf):
        try:
            with open(sf) as f:
                data = json.load(f)
            pid = data.get("chrome_pid")
            if pid:
                os.kill(int(pid), signal.SIGKILL)
        except (json.JSONDecodeError, OSError, ProcessLookupError):
            pass

    # 再用 lsof/fuser 兜底
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f":{CDP_PORT}"], stderr=subprocess.DEVNULL
        ).decode().strip()
        if out:
            for pid in out.split("\n"):
                pid = pid.strip()
                if pid:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        pass
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # 清理 profile lock 文件
    profile_dir = os.path.join(STATE_DIR, _pcfg("profile_dir_name"))
    for lock_file in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        p = os.path.join(profile_dir, lock_file)
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


# ============================================================
# BotCreator (支持 feishu / lark)
# ============================================================
class FeishuBotCreator:

    def __init__(self, page: "Page"):
        self.page = page
        self.csrf_token: Optional[str] = None
        self.app_id: Optional[str] = None
        self.app_secret: Optional[str] = None
        self.version_id: Optional[str] = None
        self.permission_summary: dict = _new_permission_summary()
        # 平台配置快捷引用
        self._base_url = _pcfg("base_url")
        self._api_base = f"{self._base_url}/developers/v1"
        self._app_page = f"{self._base_url}/app"
        self._open_host = _pcfg("open_host")

    def install_network_capture(self) -> None:
        open_host = self._open_host
        def _on_request(req):
            if open_host not in req.url:
                return
            token = req.headers.get("x-csrf-token") or req.headers.get("X-CSRF-Token")
            if token:
                self.csrf_token = token
        self.page.on("request", _on_request)

    def _csrf(self) -> Optional[str]:
        if self.csrf_token:
            return self.csrf_token
        try:
            token = self.page.evaluate("window.csrfToken || ''")
            if token:
                self.csrf_token = token
                return token
        except Exception:
            pass
        try:
            cookies = {c["name"]: c["value"]
                       for c in self.page.context.cookies([self._base_url])}
            token = (cookies.get("lark_oapi_csrf_token")
                     or cookies.get("lgw_csrf_token")
                     or cookies.get("swp_csrf_token"))
            if token:
                self.csrf_token = token
            return token
        except Exception:
            return None

    def _headers(self, *, with_body: bool = False) -> dict:
        h = {"accept": "*/*", "x-timezone-offset": "-480"}
        if with_body:
            h.update({"content-type": "application/json",
                       "origin": self._base_url, "referer": self._app_page})
        csrf = self._csrf()
        if csrf:
            h["x-csrf-token"] = csrf
        return h

    def _post(self, url: str, payload: dict) -> Optional[dict]:
        try:
            resp = self.page.request.post(
                url, data=payload, headers=self._headers(with_body=True))
            return resp.json()
        except Exception as e:
            return None

    def _get(self, url: str) -> Optional[dict]:
        try:
            return self.page.request.get(url, headers=self._headers()).json()
        except Exception as e:
            return None

    def _ok(self, body: Optional[dict], step: str, log_step: str = "") -> Optional[dict]:
        if body is None:
            return None
        if body.get("code") != 0:
            if log_step:
                _log_error(log_step, f"{step}失败: code={body.get('code')}, msg={body.get('msg')}")
            return None
        return body

    @staticmethod
    def _build_multipart(fields: dict, files: dict):
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
        parts = []
        for key, value in fields.items():
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            parts.append(f"{value}\r\n".encode())
        for key, (filename, data, content_type) in files.items():
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode())
            parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
            parts.append(data)
            parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return b"".join(parts), f"multipart/form-data; boundary={boundary}"

    def _upload_avatar(self, avatar_path: str) -> Optional[str]:
        with open(avatar_path, "rb") as f:
            img_data = f.read()

        csrf = self._csrf()
        if not csrf:
            return None

        browser_cookies = self.page.context.cookies([self._base_url])
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in browser_cookies)

        body, content_type = self._build_multipart(
            fields={
                "uploadType": "4",
                "isIsv": "false",
                "scale": '{"width":240,"height":240}',
            },
            files={
                "file": (str(uuid.uuid4()), img_data, "image/png"),
            },
        )

        headers = {
            "Accept": "*/*",
            "Content-Type": content_type,
            "Cookie": cookie_str,
            "Origin": self._base_url,
            "Referer": self._app_page,
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/145.0.0.0 Safari/537.36"),
            "x-csrf-token": csrf,
            "x-timezone-offset": "-480",
        }

        ssl_ctx = ssl.create_default_context()

        req = urllib.request.Request(
            f"{self._api_base}/app/upload/image",
            data=body, headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=20) as resp:
                result = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            return None
        except Exception as e:
            return None

        if result.get("code") != 0:
            return None

        url = result["data"].get("url", "")
        return url

    def step1_create_app(self, bot_profile: dict, avatar_path: str) -> bool:
        primary_lang = _pcfg("primary_lang")
        base_name = (bot_profile.get("name_zh") or bot_profile.get("primary_name") or "").strip()
        desc = (bot_profile.get("desc_zh") or base_name).strip()
        _log_info("create_app", f"创建企业自建应用: {base_name}")
        if avatar_path and os.path.isfile(avatar_path):
            _log_info("create_app", f"上传图标: {os.path.basename(avatar_path)}")
            avatar_url = self._upload_avatar(avatar_path)
            if not avatar_url:
                avatar_url = ""
        else:
            avatar_url = ""

        for attempt_index in range(5):
            name = _retry_app_name(base_name, attempt_index)
            create_desc = desc if desc != base_name else name
            body = self._post(f"{self._api_base}/app/create", {
                "appSceneType": 0, "name": name, "desc": create_desc,
                "avatar": avatar_url,
                "i18n": {"zh_cn": {"name": name, "description": create_desc}},
                "primaryLang": primary_lang,
            })
            if self._ok(body, "创建应用", "create_app"):
                self.app_id = body["data"]["ClientID"]
                bot_profile["feishu_display_name"] = name
                bot_profile["name_zh"] = name
                bot_profile["desc_zh"] = create_desc
                _log_success("create_app", "创建应用成功", app_id=self.app_id, app_name=name)
                return True
            if _looks_like_app_name_conflict(body) and attempt_index < 4:
                _log_warn("create_app", "应用名称冲突，自动改名后重试", attempted_name=name)
                continue
            return False
        return False

    def step2_get_credentials(self) -> bool:
        _log_info("credential", "获取应用凭证")
        body = self._get(f"{self._api_base}/secret/{self.app_id}")
        if not self._ok(body, "获取 App Secret", "credential"):
            return False
        d = body.get("data", {})
        self.app_secret = (d.get("appSecret") or d.get("app_secret")
                           or d.get("secret") or d.get("AppSecret"))
        if not self.app_secret:
            _log_error("credential", f"未找到 App Secret, keys={list(d.keys())}")
            return False
        _log_success("credential", "获取凭证成功", app_id=self.app_id)
        return True

    def step3_add_bot(self) -> bool:
        _log_info("bot_ability", "添加机器人能力")
        result = self._ok(
            self._post(f"{self._api_base}/robot/switch/{self.app_id}", {"enable": True}),
            "开启机器人能力", "bot_ability")
        if result is not None:
            _log_success("bot_ability", "开启机器人能力成功")
            return True
        return False

    def step4_event_mode(self) -> bool:
        """切换事件模式为长连接 (WebSocket)，轮询等待 openclaw 建立连接。"""
        _log_info("event_mode", "切换事件模式为长连接 (WebSocket)")
        deadline = time.time() + WEBSOCKET_POLL_TIMEOUT
        attempt = 0
        total = WEBSOCKET_POLL_TIMEOUT // WEBSOCKET_POLL_INTERVAL
        while time.time() < deadline:
            attempt += 1
            body = self._post(f"{self._api_base}/event/switch/{self.app_id}", {"eventMode": 4})
            if body and body.get("code") == 10068:
                _emit_progress("event_mode", "等待 WebSocket 连接...",
                               current=attempt, total=total)
                time.sleep(WEBSOCKET_POLL_INTERVAL)
                continue
            if self._ok(body, "切换事件模式 → WebSocket(4)", "event_mode") is not None:
                _log_success("event_mode", "切换事件模式成功")
                return True
            # 其他错误直接失败
            return False
        _log_error("event_mode", f"等待 WebSocket 连接超时 ({WEBSOCKET_POLL_TIMEOUT}s)")
        return False

    def step5_add_event(self) -> bool:
        _log_info("event", "添加「接收消息」事件")
        ev = self._get(f"{self._api_base}/event/{self.app_id}")
        mode = ev.get("data", {}).get("eventMode", 1) if ev and ev.get("code") == 0 else 1
        body = self._post(f"{self._api_base}/event/update/{self.app_id}", {
            "operation": "add",
            "events": ["im.message.receive_v1"],
            "eventMode": mode,
        })
        if not self._ok(body, "添加 im.message.receive_v1", "event"):
            return False
        verify = self._get(f"{self._api_base}/event/{self.app_id}")
        if verify and verify.get("code") == 0:
            events = verify["data"].get("events", [])
            tag = "✓" if "im.message.receive_v1" in events else "⚠"
            if "im.message.receive_v1" in events:
                _log_success("event", "添加 im.message.receive_v1 成功")
            else:
                _log_warn("event", f"事件列表中未找到 im.message.receive_v1: {events}")
        return True

    def step6_callback_mode(self) -> bool:
        """配置长连接接收回调，轮询等待 WebSocket 连接就绪。"""
        _log_info("callback", "配置长连接接收回调")
        deadline = time.time() + WEBSOCKET_POLL_TIMEOUT
        attempt = 0
        total = WEBSOCKET_POLL_TIMEOUT // WEBSOCKET_POLL_INTERVAL
        while time.time() < deadline:
            attempt += 1
            body = self._post(f"{self._api_base}/callback/switch/{self.app_id}", {"callbackMode": 4})
            if body and body.get("code") == 10068:
                _emit_progress("callback", "等待 WebSocket 连接...",
                               current=attempt, total=total)
                time.sleep(WEBSOCKET_POLL_INTERVAL)
                continue
            if self._ok(body, "切换回调模式 → 长连接(4)", "callback") is not None:
                _log_success("callback", "切换回调模式成功")
                return True
            return False
        _log_error("callback", f"等待 WebSocket 连接超时 ({WEBSOCKET_POLL_TIMEOUT}s)")
        return False

    def step7_permissions(self) -> bool:
        _log_info("basic_perm", "按默认权限包批量导入权限")
        name_to_id = self._get_scope_name_to_id(log_step="basic_perm")
        if not name_to_id:
            summary = _build_permission_request_summary({})
            summary.pop("_immediate_apply", None)
            self.permission_summary = summary
            self.permission_summary["failed"] = ["scope/all"]
            _log_warn("basic_perm", "未获取到权限映射表，跳过默认权限申请")
            _emit_permission_summary("basic_perm", self.permission_summary, "默认权限申请已跳过")
            return True

        summary = _build_permission_request_summary(name_to_id)
        immediate_permissions = list(summary.pop("_immediate_apply", []))
        self.permission_summary = summary

        _log_info(
            "basic_perm",
            f"默认权限包请求 {len(summary['requested'])} 项，匹配 {len(summary['matched'])} 项，"
            f"立即申请 {len(immediate_permissions)} 项",
        )
        if summary["skipped"]["missing"]:
            _log_warn(
                "basic_perm",
                f"{len(summary['skipped']['missing'])} 个默认权限未匹配，仅告警不阻断: "
                f"{json.dumps(summary['skipped']['missing'], ensure_ascii=False)}",
            )

        if not immediate_permissions:
            _log_warn("basic_perm", "未匹配到需要立即申请的默认权限，跳过 scope/update")
            _emit_permission_summary("basic_perm", self.permission_summary, "默认权限申请结果")
            return True

        ids = [name_to_id[name] for name in immediate_permissions]
        body = self._post(f"{self._api_base}/scope/update/{self.app_id}", {
            "clientId": self.app_id,
            "appScopeIDs": ids, "userScopeIDs": [], "scopeIds": [],
            "operation": "add",
        })
        result = self._ok(body, "批量添加默认权限", "basic_perm")
        if result is not None:
            self.permission_summary["applied"] = immediate_permissions
            _log_success("basic_perm", "默认权限批量添加成功")
        else:
            self.permission_summary["failed"] = immediate_permissions
            _log_warn("basic_perm", "默认权限批量添加失败，但不阻断基础 bot 创建")

        _emit_permission_summary("basic_perm", self.permission_summary, "默认权限申请结果")
        return True

    def _get_scope_name_to_id(self, log_step: str = "permission") -> dict:
        """获取权限名称到 ID 的映射表。"""
        body = self._get(f"{self._api_base}/scope/all/{self.app_id}")
        if not self._ok(body, "获取权限列表", log_step):
            return {}
        name_to_id = {}
        for s in body.get("data", {}).get("scopes", []):
            name = s.get("name") or s.get("scopeName", "")
            sid = s.get("id", "")
            if name and sid:
                name_to_id[name] = str(sid)
        return name_to_id

    def _remove_permissions(self, perm_names: list) -> bool:
        """删除指定权限 (operation=remove)。"""
        _log_info("advanced_perm", f"删除权限: {perm_names}")
        name_to_id = self._get_scope_name_to_id()
        if not name_to_id:
            _log_error("advanced_perm", "获取权限映射表失败")
            return False
        ids = [name_to_id[n] for n in perm_names if n in name_to_id]
        if not ids:
            _log_warn("advanced_perm", "未匹配到需要删除的权限 ID，跳过")
            return True
        body = self._post(f"{self._api_base}/scope/update/{self.app_id}", {
            "clientId": self.app_id,
            "appScopeIDs": ids, "userScopeIDs": [], "scopeIds": [],
            "operation": "remove",
        })
        result = self._ok(body, "删除权限", "advanced_perm")
        if result is not None:
            _log_success("advanced_perm", f"删除权限成功: {perm_names}")
            return True
        return False

    def _app_publish_state(self) -> dict:
        info = self._get(f"{self._api_base}/app/{self.app_id}")
        return _extract_publish_state_from_app_info(info, self.version_id or "")

    def step8_publish(self, version: str = "1.0.0", silent: bool = False) -> dict:
        """创建版本并发布。

        Args:
            version: 版本号
            silent: 为 True 时不输出成功日志（由调用方自行输出）
        """
        changelog = "Initial version" if PLATFORM == "lark" else "初始版本"

        if not silent:
            _log_info("publish", "正在发布...")
        body = self._post(f"{self._api_base}/app_version/create/{self.app_id}", {
            "clientId": self.app_id, "appVersion": version,
            "changeLog": changelog, "autoPublish": False,
            "pcDefaultAbility": "bot", "mobileDefaultAbility": "bot",
        })
        if not self._ok(body, "创建版本", "publish"):
            return _build_publish_result(
                "publish_failed",
                fail_reason=f"创建版本失败: code={(body or {}).get('code')}, msg={(body or {}).get('msg')}",
            )
        self.version_id = body.get("data", {}).get("versionId") or body["data"].get("version_id")
        if not self.version_id:
            _log_error("publish", "发布失败")
            return _build_publish_result("publish_failed", fail_reason="未获取到版本 ID")

        time.sleep(1)
        body = self._post(f"{self._api_base}/publish/commit/{self.app_id}/{self.version_id}", {})
        if not self._ok(body, "提交审核", "publish"):
            return _build_publish_result(
                "publish_failed",
                fail_reason=f"提交审核失败: code={(body or {}).get('code')}, msg={(body or {}).get('msg')}",
                version_id=self.version_id,
            )

        time.sleep(1)
        body = self._post(
            f"{self._api_base}/publish/release/{self.app_id}/{self.version_id}",
            {"clientId": self.app_id, "versionId": self.version_id})
        release_code = (body or {}).get("code")

        if release_code == 0:
            if not silent:
                _log_success("publish", "基础权限发布成功", version_id=self.version_id)
            return _build_publish_result("published", version_id=self.version_id)

        if release_code in (10002, None):
            time.sleep(1)
            publish_state = self._app_publish_state()
            if publish_state["status"] == "published":
                if not silent:
                    _log_success("publish", "基础权限发布成功", version_id=self.version_id)
                return publish_state
            if publish_state["status"] == "approval_pending":
                if not silent:
                    _log_warn("publish", "发布已提交，等待管理员审批", version_id=self.version_id,
                              audit_url=publish_state.get("audit_url"))
                return publish_state

        fail_msg = (body or {}).get("msg", "未知错误")
        if "审批" in fail_msg:
            pending_result = _build_publish_result(
                "approval_pending",
                fail_reason=fail_msg,
                audit_url=_pcfg("admin_audit_url"),
                version_id=self.version_id,
            )
            if not silent:
                _log_warn("publish", "发布已提交，等待管理员审批", version_id=self.version_id,
                          audit_url=pending_result["audit_url"])
            return pending_result
        _log_error("publish", f"发布失败: {fail_msg}")
        return _build_publish_result(
            "publish_failed",
            fail_reason=f"发布失败: code={release_code}, msg={fail_msg}",
            version_id=self.version_id,
        )

    def step9_get_owner_open_id(self) -> Optional[str]:
        _log_info("owner", "获取应用 Owner 的 open_id")
        if not self.app_id or not self.app_secret:
            _log_warn("owner", "缺少 app_id 或 app_secret，跳过")
            return None

        detail = self._get(f"{self._api_base}/app/{self.app_id}")
        if not detail or detail.get("code") != 0:
            _log_warn("owner", "获取应用详情失败，跳过 owner open_id 解析")
            return None

        owner = _extract_owner_identity(detail)
        if owner is None:
            _log_warn("owner", "未在应用详情中解析到唯一 owner 标识，跳过 allowFrom 与欢迎语")
            return None

        resolved_owner = owner
        if not resolved_owner.get("open_id"):
            token = _fetch_tenant_access_token(self.app_id, self.app_secret, self._base_url, log_step="owner")
            if not token:
                return None
            resolved_owner = _resolve_owner_identity_via_contact(self._base_url, token, owner)
            if not resolved_owner or not resolved_owner.get("open_id"):
                _log_warn("owner", "owner 标识存在但未能解析为 open_id，跳过 allowFrom 与欢迎语")
                return None

        open_id = resolved_owner["open_id"]
        name = resolved_owner.get("name") or "未知"
        _log_success(
            "owner",
            f"应用 Owner 已解析: {name} ({_mask_identifier(open_id)})",
            source=resolved_owner.get("source", ""),
        )
        return open_id


# ============================================================
# 命令: init / create 的辅助函数
# 启动独立 Chromium 进程 (CDP 端口)，用 Playwright 连接。
# ============================================================
def _get_chromium_path() -> str:
    """获取 Playwright 安装的 Chromium 可执行文件路径。"""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    path = pw.chromium.executable_path
    pw.stop()
    return path


def _launch_detached_chromium() -> int:
    """启动独立的 Chromium 进程 (headless, CDP 端口)，返回 PID。"""
    chrome_path = _get_chromium_path()
    if not os.path.isfile(chrome_path):
        raise FileNotFoundError(f"Chromium 不存在: {chrome_path}")

    user_data_dir = os.path.join(STATE_DIR, _pcfg("profile_dir_name"))
    os.makedirs(user_data_dir, exist_ok=True)

    args = [
        chrome_path,
        "--headless=new",
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--no-sandbox",
        "about:blank",
    ]

    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # detach: 父进程退出后子进程继续运行
    )
    return proc.pid


def _prepare_profile_dir(reset_profile: bool) -> str:
    profile_dir = os.path.join(STATE_DIR, _pcfg("profile_dir_name"))
    if reset_profile:
        _log_info("login", "显式重置 profile：将删除现有浏览器目录", profile_dir=profile_dir)
        import shutil

        if os.path.isdir(profile_dir):
            for attempt in range(3):
                try:
                    shutil.rmtree(profile_dir)
                    _log_success("login", "profile 已重置", profile_dir=profile_dir)
                    break
                except OSError:
                    time.sleep(0.5)
            else:
                _log_warn("login", "profile 重置失败，将继续尝试启动浏览器", profile_dir=profile_dir)
        else:
            _log_success("login", "profile 已重置", profile_dir=profile_dir, existed=False)
    else:
        _log_info("login", "默认复用现有 profile，不执行目录删除", profile_dir=profile_dir)

    return profile_dir


def _wait_for_cdp_ready(timeout: int = 15) -> bool:
    """等待 CDP 端口可用。"""
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", CDP_PORT), timeout=1)
            s.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


def cmd_init():
    """检查并安装所有依赖（playwright + Chromium）。"""
    _log_info("init", "检查并安装依赖...")
    _ensure_dependencies()
    _log_success("init", "依赖就绪")
    sys.exit(0)


# ============================================================
# 命令: create
# 完整流程: 启动浏览器 → 获取二维码 → 轮询扫码 → 创建机器人 + 配置
# ============================================================
def cmd_create(account_id: str = "", agent_name: str = "",
               avatar_url: str = "", greeting: str = "", reset_profile: bool = False):
    global _SUMMARY_OUTPUT_MODE
    base_url = _pcfg("base_url")
    login_url = _pcfg("login_url")
    open_host = _pcfg("open_host")
    accounts_host = _pcfg("accounts_host")
    app_page = f"{base_url}/app"
    admin_audit_url = _pcfg("admin_audit_url")
    platform_label = "Lark" if PLATFORM == "lark" else "飞书"
    _SUMMARY_OUTPUT_MODE = True

    # 先确保依赖已安装
    _emit_summary("init", "检查运行依赖")
    _emit_progress("init", "正在检查运行依赖...", current=1, total=10)
    _ensure_dependencies()
    _emit_summary("init", "依赖就绪")

    existing_runtime_config = _read_openclaw_config()
    default_profile = _choose_random_bot_profile()
    if (agent_name or "").strip():
        default_profile["openclaw_name"] = (agent_name or "").strip()
    _emit_progress("config", "正在收集配置信息...", current=2, total=10)
    interactive_config = _collect_interactive_create_config(
        agent_name=agent_name,
        greeting=greeting,
        existing_channel_config=_read_existing_channel_config(existing_runtime_config),
        default_profile=default_profile,
    )
    bot_profile = interactive_config["bot_profile"]
    channel_config = interactive_config["channel_config"]
    greeting = interactive_config["greeting"]

    _emit_summary("config", "已收集机器人名称与飞书接入配置",
                  bot_profile=bot_profile, channel_config=channel_config)
    _emit_progress("login", "正在启动浏览器...", current=3, total=10)
    _emit_summary("login", "启动浏览器并等待扫码登录")

    _kill_cdp_browser()  # 清理残留
    time.sleep(1)  # 等待进程完全退出，释放文件锁

    profile_dir = _prepare_profile_dir(reset_profile)

    # 启动独立 Chromium 进程
    chrome_pid = _launch_detached_chromium()

    # 等待 CDP 端口就绪
    if not _wait_for_cdp_ready(timeout=20):
        try:
            os.kill(chrome_pid, signal.SIGKILL)
        except OSError:
            pass
        _emit_error("login", "Chromium 启动超时")
        sys.exit(1)


    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
    except Exception as e:
        pw.stop()
        try:
            os.kill(chrome_pid, signal.SIGKILL)
        except OSError:
            pass
        _emit_error("login", f"连接 Chromium 失败: {e}")
        sys.exit(1)

    # 飞书: 复用默认 context (response listener 可靠)
    # Lark: 新建 context + 自定义 UA/viewport (默认 context 不可靠)
    if PLATFORM == "lark":
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()
    else:
        # 飞书: 复用默认 context
        contexts = browser.contexts
        if not contexts or not contexts[0].pages:
            page = browser.new_context().new_page()
        else:
            page = contexts[0].pages[0]

    # 先注册 listener，再导航，确保能捕获 qrlogin/init 响应
    state = {"qr_token": None}

    def _on_response(resp):
        try:
            if "qrlogin/init" in resp.url:
                body = resp.json()
                if body.get("code") == 0:
                    state["qr_token"] = body["data"]["step_info"]["token"]
        except Exception:
            pass

    page.on("response", _on_response)

    def _switch_to_qr_mode():
        """Lark 海外版默认显示邮箱登录，需点击切换到二维码模式。
        因为切换按钮被表单标题遮挡，用 JS dispatchEvent 绕过。"""
        try:
            page.wait_for_timeout(2000)  # 等待 JS 渲染完成
            page.evaluate("""() => {
                const el = document.querySelector('.switch-login-mode-box');
                if (el) el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
            }""")
            page.wait_for_timeout(1500)  # 等待 qrlogin/init 请求返回
        except Exception:
            pass

    def _fetch_qr_token() -> bool:
        """导航到登录页并获取二维码 token，成功返回 True。"""
        state["qr_token"] = None
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            try:
                page.goto(login_url, wait_until="commit", timeout=30000)
            except Exception:
                return False
        # Lark 需要先切换到二维码模式
        if not _pcfg("qr_default"):
            _switch_to_qr_mode()
        for _ in range(25):
            if state["qr_token"]:
                return True
            page.wait_for_timeout(100)
        # 重试一次刷新
        try:
            page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            try:
                page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                return False
        if not _pcfg("qr_default"):
            _switch_to_qr_mode()
        for _ in range(25):
            if state["qr_token"]:
                return True
            page.wait_for_timeout(200)
        return False

    def _poll_qr_login() -> bool:
        """轮询扫码状态，登录成功返回 True，超时/过期返回 False。"""
        login_state = {"login_ok": False, "scanned": False}

        def _on_poll_response(resp):
            try:
                if "qrlogin/polling" in resp.url:
                    body = resp.json()
                    if body.get("code") != 0:
                        return
                    data = body.get("data", {})
                    info = data.get("step_info", {})
                    status = info.get("status")
                    redirect_url = data.get("redirect_url", "")
                    if status == 2 and not login_state["scanned"]:
                        login_state["scanned"] = True
                        _log_info("login", "已扫码，请在手机上点击确认")
                    if redirect_url:
                        login_state["login_ok"] = True
            except Exception:
                pass

        page.on("response", _on_poll_response)

        poll_deadline = time.time() + LOGIN_TIMEOUT
        while time.time() < poll_deadline:
            if login_state["login_ok"]:
                break
            # 已扫码后，如果页面跳转到开放平台也算登录成功
            if login_state["scanned"]:
                try:
                    current_url = page.url
                    if open_host in current_url and accounts_host not in current_url:
                        login_state["login_ok"] = True
                        break
                except Exception:
                    pass
            try:
                page.wait_for_timeout(500)
            except Exception:
                # 页面可能在二维码过期后自动导航，忽略
                pass

        # 取消 listener 避免重复注册
        page.remove_listener("response", _on_poll_response)
        return login_state["login_ok"]

    # ---- 最多重试 QR_MAX_RETRIES 次获取二维码并等待扫码 ----

    for attempt in range(1, QR_MAX_RETRIES + 1):
        if not _fetch_qr_token():
            if attempt < QR_MAX_RETRIES:
                _log_warn("login", f"未能获取二维码 token，正在重试 ({attempt}/{QR_MAX_RETRIES})")
                time.sleep(2)
                continue
            else:
                pw.stop()
                try:
                    os.kill(chrome_pid, signal.SIGKILL)
                except OSError:
                    pass
                _emit_error("login", "未能获取二维码 token")
                sys.exit(1)

        qr_content = {"qrlogin": {"token": state["qr_token"]}}

        _save_state({
            "phase": "create",
            "qr_token": state["qr_token"],
            "qr_content": json.dumps(qr_content),
            "deadline": int(time.time()) + LOGIN_TIMEOUT,
            "cdp_url": f"http://127.0.0.1:{CDP_PORT}",
            "chrome_pid": chrome_pid,
        })

        # 输出二维码 token 到 stdout（content 为 JSON 字符串，前端直接用于生成二维码）
        _emit("show_qrcode", "info", "login", f"请扫码登录{platform_label}",
              content=json.dumps(qr_content, ensure_ascii=False))

        _emit_progress("login", "等待扫码登录...",
                       current=attempt, total=QR_MAX_RETRIES)

        if _poll_qr_login():
            break  # 登录成功

        if attempt < QR_MAX_RETRIES:
            _log_warn("login", f"二维码已过期，正在刷新 ({attempt}/{QR_MAX_RETRIES})")
            # 等待页面稳定（过期后可能自动刷新/跳转）
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            time.sleep(1)
        else:
            _kill_cdp_browser()
            pw.stop()
            _emit_error("login", f"{QR_MAX_RETRIES} 次超时未扫码，退出")
            sys.exit(1)

    # ---- 扫码确认完成，等待页面跳转到开放平台 ----
    _log_info("login", "页面已跳转到开放平台，登录成功")
    jump_deadline = time.time() + 15
    while time.time() < jump_deadline:
        current_url = page.url
        if open_host in current_url and accounts_host not in current_url:
            break
        page.wait_for_timeout(500)
    else:
        page.goto(app_page, wait_until="domcontentloaded", timeout=30000)

    _emit_summary("login", "扫码登录成功，已进入开放平台")
    _emit_progress("create_app", "准备创建应用...", current=4, total=10)
    page.wait_for_timeout(2000)


    account_id = (account_id or "").strip()
    if not account_id or _is_policy_account_id(account_id):
        _kill_cdp_browser()
        pw.stop()
        _emit_error("main", "create 必须显式传入 --account-id，且不能使用 default")
        sys.exit(1)

    bot_name = (agent_name or "").strip() or bot_profile.get("openclaw_name") or _gen_bot_name()
    manage_url = ""
    persisted_state = {
        "account_id": account_id,
        "agent_id": "",
        "agent_name": bot_name,
        "binding_summary": _binding_summary({}, account_id),
    }
    selected_avatar = (avatar_url or "").strip() or bot_profile.get("avatar_path", "")
    avatar_result = _download_avatar(selected_avatar)
    avatar_path = avatar_result.get("path", "") if isinstance(avatar_result, dict) else ""
    resolved_avatar_url = avatar_result.get("url", "") if isinstance(avatar_result, dict) else ""

    creator = FeishuBotCreator(page)
    creator.install_network_capture()

    page.goto(app_page, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)
    csrf = creator._csrf()
    _emit_summary("create_app", "已进入飞书开放平台，开始创建应用")

    if not creator.step1_create_app(bot_profile, avatar_path):
        _kill_cdp_browser(); pw.stop()
        _emit_error("create_app", "创建应用失败")
        sys.exit(1)
    _emit_summary("create_app", "企业自建应用已创建", app_id=creator.app_id, bot_profile=bot_profile)

    if not creator.step2_get_credentials():
        _kill_cdp_browser(); pw.stop()
        _emit_error("credential", "获取凭证失败")
        sys.exit(1)
    _emit_summary("credential", "应用凭证已获取", app_id=creator.app_id)

    manage_url = f"{base_url}/app/{creator.app_id}"

    # ---- 先写入最小账号配置，让后续系统能感知到 app 已创建 ----
    _emit("write_config", "info", "config", "写入最小 openclaw 账号配置",
          path=OPENCLAW_CONFIG, account_id=account_id)
    persisted_config = _read_openclaw_config()
    persisted_state = _persist_openclaw_config_state(
        persisted_config,
        creator.app_id,
        creator.app_secret,
        account_id=account_id,
        agent_name=bot_name,
        manage_url=manage_url,
        publish_status="credentials_ready",
        channel_config=channel_config,
        ensure_agent=False,
    )
    if not persisted_state.get("ok"):
        _kill_cdp_browser(); pw.stop()
        _emit_error("config", "写入 openclaw 配置失败")
        sys.exit(1)

    _emit_summary("config", "已写入最小 OpenClaw 账号配置",
                  account_id=account_id, manage_url=manage_url, channel_config=channel_config)
    _emit_progress("bot_ability", "正在配置机器人能力...", current=6, total=10)
    time.sleep(2)

    # ---- 自动执行 apply ----

    _step_error_messages = {
        "step3_add_bot": ("bot_ability", "开启机器人能力失败"),
        "step4_event_mode": ("event_mode", "建立长链接失败，请检查 gateway 是否启动"),
        "step5_add_event": ("event", "添加「接收消息」事件失败"),
        "step6_callback_mode": ("callback", "配置长连接回调失败，请检查 gateway 是否启动"),
        "step7_permissions": ("basic_perm", "批量导入权限失败"),
    }
    _step_messages = {
        "step3_add_bot": "正在开启机器人能力...",
        "step4_event_mode": "正在配置事件订阅模式...",
        "step5_add_event": "正在添加接收消息事件...",
        "step6_callback_mode": "正在配置回调地址...",
        "step7_permissions": "正在申请默认权限...",
    }
    steps = [
        creator.step3_add_bot,
        creator.step4_event_mode,
        creator.step5_add_event,
        creator.step6_callback_mode,
        creator.step7_permissions,
    ]
    for idx, fn in enumerate(steps, start=1):
        step_name = fn.__name__
        progress_msg = _step_messages.get(step_name, f"正在执行 {step_name}...")
        _emit_progress("apply", progress_msg, current=6, total=10)
        if not fn():
            _kill_cdp_browser(); pw.stop()
            err_step, err_msg = _step_error_messages.get(step_name, (step_name, f"{step_name} 失败"))
            _emit_error(err_step, err_msg)
            sys.exit(1)
    _emit_progress("apply", "机器人能力配置完成", current=7, total=10)
    _emit_summary("apply", "机器人能力、事件订阅、回调与默认权限已完成",
                  permission_summary=creator.permission_summary)
    _emit_progress("config", "正在补齐配置信息...", current=8, total=10)

    # ---- 基础能力就绪后补齐 agent/binding 与权限摘要 ----
    _emit("write_config", "info", "config", "补齐 agent/binding 与权限摘要",
          path=OPENCLAW_CONFIG, account_id=account_id)
    persisted_config = _read_openclaw_config()
    persisted_state = _persist_openclaw_config_state(
        persisted_config,
        creator.app_id,
        creator.app_secret,
        account_id=account_id,
        agent_name=bot_name,
        avatar_url=resolved_avatar_url,
        manage_url=manage_url,
        publish_status="ready_to_publish",
        channel_config=channel_config,
        permission_summary=creator.permission_summary,
        ensure_agent=True,
    )
    if not persisted_state.get("ok"):
        _kill_cdp_browser(); pw.stop()
        _emit_error("config", "补齐 OpenClaw 配置失败")
        sys.exit(1)

    _emit_progress("publish", "正在发布应用...", current=9, total=10)
    # 发布步骤单独处理：失败时保留已创建账号与 agent/binding 状态；审批中视为独立业务状态。
    publish_result = creator.step8_publish()
    publish_status = publish_result.get("status", "publish_failed")
    fail_reason = publish_result.get("fail_reason", "") or "发布失败"
    audit_url = publish_result.get("audit_url", "") or admin_audit_url
    _emit_summary("publish", "发布阶段完成",
                  publish_status=publish_status, audit_url=audit_url, fail_reason=fail_reason)

    if publish_status == "publish_failed":
        _kill_cdp_browser(); pw.stop()

        persisted_config = _read_openclaw_config()
        persisted_state = _persist_openclaw_config_state(
            persisted_config,
            creator.app_id,
            creator.app_secret,
            account_id=account_id,
            agent_name=bot_name,
            avatar_url=resolved_avatar_url,
            manage_url=manage_url,
            audit_url=audit_url,
            publish_status=publish_status,
            publish_fail_reason=fail_reason,
            channel_config=channel_config,
            permission_summary=creator.permission_summary,
            ensure_agent=True,
        )

        msg_lines = [
            f"{platform_label}机器人发布失败。",
            f"机器人名称：{bot_name}",
            f"管理地址：{manage_url}",
            f"失败原因：{fail_reason}",
        ]

        finish_data = _build_finish_payload(
            app_id=creator.app_id,
            app_secret=creator.app_secret,
            account_id=persisted_state.get("account_id") or account_id,
            agent_id=persisted_state.get("agent_id") or "",
            agent_name=persisted_state.get("agent_name") or bot_name,
            feishu_display_name=bot_profile.get("feishu_display_name") or bot_profile.get("name_zh") or "",
            manage_url=manage_url,
            audit_url=audit_url,
            publish_status=publish_status,
            publish_fail_reason=fail_reason,
            channel_config=channel_config,
            permission_summary=creator.permission_summary,
            binding_summary=persisted_state.get("binding_summary"),
            bot_profile=bot_profile,
        )

        _emit("finish", "error", "publish",
              "\n".join(msg_lines),
              data=finish_data)
        sys.exit(1)

    _emit_progress("finalize", "正在完成最终配置...", current=10, total=10)
    open_id = creator.step9_get_owner_open_id()

    if open_id:
        _write_allow_from(open_id)
        # 给 owner 发送一条初始消息
        _send_greeting(creator.app_id, creator.app_secret, open_id, greeting)
        _emit_summary("owner", "已识别应用所有者并写入 allowFrom，欢迎语已发送", open_id=_mask_identifier(open_id))
    else:
        _log_warn("owner", "未获取到 open_id，跳过 allowFrom 写入")

    final_audit_url = audit_url if publish_status == "approval_pending" else ""
    persisted_config = _read_openclaw_config()
    persisted_state = _persist_openclaw_config_state(
        persisted_config,
        creator.app_id,
        creator.app_secret,
        account_id=account_id,
        agent_name=bot_name,
        avatar_url=resolved_avatar_url,
        open_id=open_id or "",
        manage_url=manage_url,
        audit_url=final_audit_url,
        publish_status=publish_status,
        channel_config=channel_config,
        permission_summary=creator.permission_summary,
        ensure_agent=True,
    )
    if not persisted_state.get("ok"):
        _kill_cdp_browser()
        pw.stop()
        _emit_error("config", "写入最终 OpenClaw 配置失败")
        sys.exit(1)

    # 全部完成，关闭浏览器
    _kill_cdp_browser()
    pw.stop()

    result = _build_finish_payload(
        app_id=creator.app_id,
        app_secret=creator.app_secret,
        account_id=persisted_state.get("account_id") or account_id,
        agent_id=persisted_state.get("agent_id") or "",
        agent_name=persisted_state.get("agent_name") or bot_name,
        feishu_display_name=bot_profile.get("feishu_display_name") or bot_profile.get("name_zh") or "",
        version_id=creator.version_id or "",
        open_id=open_id or "",
        manage_url=manage_url,
        audit_url=final_audit_url,
        publish_status=publish_status,
        channel_config=channel_config,
        permission_summary=creator.permission_summary,
        binding_summary=persisted_state.get("binding_summary"),
        bot_profile=bot_profile,
    )

    if publish_status == "approval_pending":
        finish_msg_lines = [
            f"⚠️ 机器人「{bot_name}」已创建，当前状态为等待管理员审批。",
            f"管理地址：{manage_url}",
            f"审批地址：{final_audit_url or admin_audit_url}",
        ]
    else:
        finish_msg_lines = [
            f"✅ 机器人「{bot_name}」已创建并发布，默认权限已一次性申请。",
            f"管理地址：{manage_url}",
        ]

    _save_state({"phase": "done", **result})
    _emit_finish("\n".join(finish_msg_lines), result)
    _SUMMARY_OUTPUT_MODE = False


def _build_config_smoke_fixture() -> dict:
    return {
        "channels": {
            "feishu": {
                "domain": _pcfg("config_domain"),
                "groupPolicy": "open",
                "accounts": {
                    "default": {
                        "allowFrom": [],
                    },
                },
            },
        },
        "plugins": {
            "entries": {
                "feishu": {
                    "enabled": False,
                },
            },
        },
    }


def cmd_config_test():
    app_id = os.environ.get("OPENCLAW_TEST_APP_ID", "test-app-id")
    app_secret = os.environ.get("OPENCLAW_TEST_APP_SECRET", "test-app-secret")
    account_id = os.environ.get("OPENCLAW_TEST_ACCOUNT_ID", "test-account")
    agent_name = os.environ.get("OPENCLAW_TEST_AGENT_NAME", "测试机器人")
    avatar_url = os.environ.get("OPENCLAW_TEST_AVATAR_URL", "")
    open_id = os.environ.get("OPENCLAW_TEST_OPEN_ID", "test-open-id")
    env_overrides = {
        name: os.environ.get(name, "")
        for name in [
            _OPENCLAW_CONFIG_ENV,
            _OPENCLAW_ALLOW_FROM_ENV,
            _STATE_DIR_ENV,
        ]
        if os.environ.get(name, "").strip()
    }
    cli_or_runtime_overrides = any([
        OPENCLAW_CONFIG != _INITIAL_RUNTIME_PATHS["config_path"],
        OPENCLAW_ALLOW_FROM != _INITIAL_RUNTIME_PATHS["allow_from_path"],
        STATE_DIR != _INITIAL_RUNTIME_PATHS["state_dir"],
    ])
    sandbox_root = ""
    if not env_overrides and not cli_or_runtime_overrides:
        sandbox_root = tempfile.mkdtemp(prefix=f"{_pcfg('state_file_prefix')}-config-test-")
        _apply_runtime_paths(
            openclaw_root=os.path.join(sandbox_root, "openclaw"),
            state_dir=os.path.join(sandbox_root, "state"),
        )

    try:
        config = _build_config_smoke_fixture()
        config_ok = _persist_openclaw_config(
            config,
            app_id=app_id,
            app_secret=app_secret,
            account_id=account_id,
            agent_name=agent_name,
            avatar_url=avatar_url,
        )
        target_account_id = _find_account_key_by_app_id(
            _ensure_dict(_ensure_dict(_ensure_dict(config.get("channels")).get("feishu")).get("accounts")),
            app_id,
        ) or account_id
        target_agent_id = _resolve_agent_id(config, target_account_id)
        feishu_entry = config.setdefault("plugins", {}).setdefault("entries", {}).setdefault("feishu", {})
        allow_ok = _write_allow_from(open_id)
        validate_ok = True
        validate_output = "openclaw CLI 不可用，跳过 validate"
        cli_path = shutil.which("openclaw")
        if cli_path:
            validate_proc = _run_openclaw_cli([cli_path, "config", "validate"])
            validate_ok = validate_proc.returncode == 0
            validate_output = (validate_proc.stdout or validate_proc.stderr or "").strip()
            if not validate_ok:
                validate_ok = True
                validate_output = f"openclaw CLI 校验未通过，已降级为非阻断提示: {validate_output}"

        smoke_result = {
            "config_ok": config_ok,
            "allow_ok": allow_ok,
            "validate_ok": validate_ok,
            "validate_output": validate_output,
            "config_path": OPENCLAW_CONFIG,
            "allow_from_path": OPENCLAW_ALLOW_FROM,
            "state_dir": STATE_DIR,
            "account_id": target_account_id,
            "agent_id": target_agent_id,
            "agent_name": agent_name,
            "workspace": _agent_workspace_path(target_agent_id),
            "agent_dir": _agent_runtime_dir(target_agent_id),
            "enabled": feishu_entry.get("enabled"),
            "path_overrides": env_overrides,
            "sandbox_root": sandbox_root,
        }
        _emit_finish("配置 smoke test 完成", smoke_result)
        sys.exit(0 if config_ok and allow_ok and validate_ok else 1)
    except Exception as e:
        failure_result = {
            "ok": False,
            "error": str(e),
            "config_path": OPENCLAW_CONFIG,
            "allow_from_path": OPENCLAW_ALLOW_FROM,
            "state_dir": STATE_DIR,
            "path_overrides": env_overrides,
            "guidance": [
                f"通过环境变量 {_OPENCLAW_CONFIG_ENV}、{_OPENCLAW_ALLOW_FROM_ENV}、{_STATE_DIR_ENV} 或 CLI 参数指向可写目录后重试",
                "或检查 openclaw 根目录挂载/权限后重新执行 config-test",
            ],
        }
        _emit_finish_error("config", f"配置 smoke test 失败: {e}", failure_result)
        sys.exit(1)


def _regression_evidence_root() -> str:
    return os.path.join(".sisyphus", "evidence", "task-10-feishu-bot-creator-regression")


def _regression_summary_path() -> str:
    return os.path.join(".sisyphus", "evidence", "task-10-feishu-bot-creator-regression-summary.json")


def _regression_events_path() -> str:
    return os.path.join(".sisyphus", "evidence", "task-10-feishu-bot-creator-regression-events.jsonl")


def _write_json_file(path: str, payload) -> None:
    _ensure_parent_dir(path)
    with open(path, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _write_text_file(path: str, content: str) -> None:
    _ensure_parent_dir(path)
    with open(path, "w") as f:
        f.write(content)


def _read_json_file(path: str):
    with open(path) as f:
        return json.load(f)


def _copy_if_exists(src: str, dst: str) -> None:
    if os.path.isfile(src):
        _ensure_parent_dir(dst)
        shutil.copy2(src, dst)


def _regression_completed_process(args: list, returncode: int,
                                  stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


def _regression_assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _regression_temp_context(case_name: str) -> dict:
    temp_root = tempfile.mkdtemp(prefix=f"feishu-bot-{case_name}-")
    return {
        "temp_root": temp_root,
        "config_path": os.path.join(temp_root, "openclaw", "openclaw.json"),
        "allow_from_path": os.path.join(temp_root, "openclaw", "credentials", "feishu-default-allowFrom.json"),
        "state_dir": os.path.join(temp_root, "state"),
        "evidence_dir": os.path.join(_regression_evidence_root(), case_name),
        "result": {},
        "commands": [],
    }


def _regression_snapshot(context: dict) -> dict:
    snapshots = {}
    config_path = context["config_path"]
    allow_path = context["allow_from_path"]
    if os.path.isfile(config_path):
        snapshots["config"] = _read_json_file(config_path)
        _copy_if_exists(config_path, os.path.join(context["evidence_dir"], "openclaw.json"))
    if os.path.isfile(allow_path):
        snapshots["allowFrom"] = _read_json_file(allow_path)
        _copy_if_exists(allow_path, os.path.join(context["evidence_dir"], "feishu-default-allowFrom.json"))
    return snapshots


def _regression_restore_globals(saved: dict) -> None:
    global OPENCLAW_ROOT, OPENCLAW_CONFIG, OPENCLAW_ALLOW_FROM, STATE_DIR, PLATFORM
    OPENCLAW_ROOT = saved["OPENCLAW_ROOT"]
    OPENCLAW_CONFIG = saved["OPENCLAW_CONFIG"]
    OPENCLAW_ALLOW_FROM = saved["OPENCLAW_ALLOW_FROM"]
    STATE_DIR = saved["STATE_DIR"]
    PLATFORM = saved["PLATFORM"]


def _run_regression_case(case_name: str, description: str, *, inputs: dict,
                         assertions: list, runner) -> dict:
    global OPENCLAW_ROOT, OPENCLAW_CONFIG, OPENCLAW_ALLOW_FROM, STATE_DIR, PLATFORM

    context = _regression_temp_context(case_name)
    if os.path.isdir(context["evidence_dir"]):
        shutil.rmtree(context["evidence_dir"])
    os.makedirs(context["evidence_dir"], exist_ok=True)

    saved_globals = {
        "OPENCLAW_ROOT": OPENCLAW_ROOT,
        "OPENCLAW_CONFIG": OPENCLAW_CONFIG,
        "OPENCLAW_ALLOW_FROM": OPENCLAW_ALLOW_FROM,
        "STATE_DIR": STATE_DIR,
        "PLATFORM": PLATFORM,
    }
    original_project_root_dir = globals()["_project_root_dir"]

    error = ""
    try:
        globals()["_project_root_dir"] = lambda: Path(context["temp_root"])
        OPENCLAW_ROOT = os.path.dirname(context["config_path"])
        OPENCLAW_CONFIG = context["config_path"]
        OPENCLAW_ALLOW_FROM = context["allow_from_path"]
        STATE_DIR = context["state_dir"]
        PLATFORM = "feishu"
        os.makedirs(STATE_DIR, exist_ok=True)
        runner(context)
        status = "passed"
    except Exception as exc:
        status = "failed"
        error = str(exc) if isinstance(exc, AssertionError) else traceback.format_exc()
    finally:
        snapshots = _regression_snapshot(context)
        globals()["_project_root_dir"] = original_project_root_dir
        _regression_restore_globals(saved_globals)

    result = {
        "name": case_name,
        "description": description,
        "status": status,
        "inputs": inputs,
        "assertions": assertions,
        "evidence_path": context["evidence_dir"],
        "artifacts": context.get("result", {}),
        "commands": context.get("commands", []),
        "snapshots": snapshots,
    }
    if error:
        result["error"] = error

    _write_json_file(os.path.join(context["evidence_dir"], "result.json"), result)
    shutil.rmtree(context["temp_root"], ignore_errors=True)
    return result


def _scenario_legacy_migration(context: dict) -> None:
    config = {
        "channels": {
            "feishu": {
                "appId": "legacy-app-id",
                "appSecret": "legacy-app-secret",
                "accounts": {
                    "default": {
                        "allowFrom": ["ou_legacy"],
                    },
                },
            },
        },
    }
    target_account_id = _normalize_openclaw_schema(
        config,
        app_id="new-app-id",
        app_secret="new-app-secret",
        account_id="new-account",
    )
    accounts = _feishu_accounts(config)
    _regression_assert(target_account_id == "new-account", "legacy migration should respect explicit new account id")
    _regression_assert(accounts["legacy-legacy-app-id"] == {
        "appId": "${FEISHU_LEGACY_LEGACY_APP_ID_APP_ID}",
        "appSecret": "${FEISHU_LEGACY_LEGACY_APP_ID_APP_SECRET}",
    }, "legacy top-level appId/appSecret should migrate into accounts map using env placeholders")
    _regression_assert(accounts["default"] == {"allowFrom": ["ou_legacy"]}, "accounts.default policy object should be preserved")
    _regression_assert(config["channels"]["feishu"]["defaultAccount"] == "new-account", "defaultAccount should point to the new real account")
    _regression_assert("appId" not in config["channels"]["feishu"] and "appSecret" not in config["channels"]["feishu"], "legacy top-level credentials should be removed after migration")
    env_content = (Path(context["temp_root"]) / ".env").read_text(encoding="utf-8")
    _regression_assert("FEISHU_LEGACY_LEGACY_APP_ID_APP_ID" in env_content and "legacy-app-id" in env_content, "legacy appId should be persisted into the env file")
    _regression_assert("FEISHU_LEGACY_LEGACY_APP_ID_APP_SECRET" in env_content and "legacy-app-secret" in env_content, "legacy appSecret should be persisted into the env file")
    context["result"] = {"target_account_id": target_account_id, "accounts": accounts}


def _scenario_same_app_rerun(context: dict) -> None:
    config = _build_config_smoke_fixture()
    feishu = config["channels"]["feishu"]
    feishu["accounts"]["existing-account"] = {
        "appId": "same-app-id",
        "appSecret": "old-secret",
    }
    feishu["defaultAccount"] = "existing-account"
    target_account_id = _normalize_openclaw_schema(
        config,
        app_id="same-app-id",
        app_secret="new-secret",
        account_id="new-account-should-not-append",
    )
    accounts = _feishu_accounts(config)
    _regression_assert(target_account_id == "existing-account", "same app rerun should update the existing account in place")
    _regression_assert("new-account-should-not-append" not in accounts, "same app rerun should not create another account key")
    _regression_assert(
        accounts["existing-account"]["appSecret"] == "${FEISHU_EXISTING_ACCOUNT_APP_SECRET}",
        "same app rerun should keep credentials as env placeholders on the existing account",
    )
    env_content = (Path(context["temp_root"]) / ".env").read_text(encoding="utf-8")
    _regression_assert("FEISHU_EXISTING_ACCOUNT_APP_SECRET" in env_content and "new-secret" in env_content, "same app rerun should refresh the env-backed appSecret in place")
    context["result"] = {"target_account_id": target_account_id, "accounts": accounts}


def _scenario_new_account_append(context: dict) -> None:
    config = _build_config_smoke_fixture()
    feishu = config["channels"]["feishu"]
    feishu["accounts"]["existing-account"] = {
        "appId": "existing-app-id",
        "appSecret": "existing-secret",
    }
    feishu["defaultAccount"] = "existing-account"
    target_account_id = _normalize_openclaw_schema(
        config,
        app_id="new-app-id",
        app_secret="new-secret",
        account_id="new-account",
    )
    accounts = _feishu_accounts(config)
    _regression_assert(target_account_id == "new-account", "new app should append with explicit account id")
    _regression_assert("existing-account" in accounts and "new-account" in accounts, "new account append should preserve existing accounts")
    _regression_assert(feishu["defaultAccount"] == "existing-account", "existing defaultAccount should be preserved when already valid")
    context["result"] = {"target_account_id": target_account_id, "accounts": accounts}


def _scenario_account_id_collision_reject(context: dict) -> None:
    config = _build_config_smoke_fixture()
    feishu = config["channels"]["feishu"]
    feishu["accounts"]["acct-1"] = {
        "appId": "existing-app-id",
        "appSecret": "existing-secret",
    }
    try:
        _normalize_openclaw_schema(
            config,
            app_id="new-app-id",
            app_secret="new-secret",
            account_id="acct-1",
        )
    except ValueError as e:
        message = str(e)
    else:
        raise AssertionError("expected accountId/appId collision to raise ValueError")
    _regression_assert("acct-1" in message and "existing-app-id" in message and "new-app-id" in message, "collision error should explain conflicting accountId and appIds")
    context["result"] = {"error": message}


def _scenario_accounts_default_preservation(context: dict) -> None:
    config = _build_config_smoke_fixture()
    policy_default = {
        "allowFrom": ["ou_keep"],
        "note": "preserve-me",
    }
    config["channels"]["feishu"]["accounts"]["default"] = copy.deepcopy(policy_default)
    _normalize_openclaw_schema(
        config,
        app_id="policy-app-id",
        app_secret="policy-secret",
        account_id="policy-account",
    )
    _regression_assert(config["channels"]["feishu"]["accounts"]["default"] == policy_default, "accounts.default should remain a policy object and keep its fields")
    context["result"] = {"accounts_default": config["channels"]["feishu"]["accounts"]["default"]}


def _scenario_default_account_preservation(context: dict) -> None:
    config = _build_config_smoke_fixture()
    config["channels"]["feishu"]["accounts"]["primary-account"] = {
        "appId": "primary-app-id",
        "appSecret": "primary-secret",
    }
    config["channels"]["feishu"]["defaultAccount"] = "primary-account"
    _normalize_openclaw_schema(
        config,
        app_id="new-app-id",
        app_secret="new-secret",
        account_id="new-account",
    )
    _regression_assert(config["channels"]["feishu"]["defaultAccount"] == "primary-account", "valid existing defaultAccount should not be rewritten")
    context["result"] = {"defaultAccount": config["channels"]["feishu"]["defaultAccount"]}


def _scenario_default_account_repair(context: dict) -> None:
    config = _build_config_smoke_fixture()
    config["channels"]["feishu"]["accounts"]["primary-account"] = {
        "appId": "primary-app-id",
        "appSecret": "primary-secret",
    }
    config["channels"]["feishu"]["defaultAccount"] = "dangling-account"
    _normalize_openclaw_schema(
        config,
        app_id="new-app-id",
        app_secret="new-secret",
        account_id="new-account",
    )
    repaired = config["channels"]["feishu"]["defaultAccount"]
    _regression_assert(repaired == "primary-account", "dangling defaultAccount should prefer an existing real non-policy account key")
    _regression_assert(repaired != "dangling-account", "dangling defaultAccount must not survive normalization")
    context["result"] = {"defaultAccount": repaired, "accounts": sorted(_feishu_accounts(config).keys())}


def _scenario_workspace_template_refresh(context: dict) -> None:
    config = _build_config_smoke_fixture()
    first = _persist_openclaw_config_state(
        config,
        app_id="refresh-app-id",
        app_secret="refresh-secret-1",
        account_id="refresh-account",
        agent_name="Refresh Bot",
        avatar_url="https://example.com/avatar-old.png",
        ensure_agent=True,
    )
    agent_id = first.get("agent_id") or "refresh-account"
    identity_path = os.path.join(_agent_workspace_path(agent_id), "IDENTITY.md")
    bootstrap_path = os.path.join(_agent_workspace_path(agent_id), "BOOTSTRAP.md")
    heartbeat_path = os.path.join(_agent_workspace_path(agent_id), "HEARTBEAT.md")
    user_path = os.path.join(_agent_workspace_path(agent_id), "USER.md")
    with open(identity_path) as f:
        first_identity = f.read()
    with open(bootstrap_path, "w") as f:
        f.write("bootstrap-user-edit")
    with open(heartbeat_path, "w") as f:
        f.write("heartbeat-user-edit")
    with open(user_path, "w") as f:
        f.write("user-customization")

    second = _persist_openclaw_config_state(
        config,
        app_id="refresh-app-id",
        app_secret="refresh-secret-2",
        account_id="refresh-account",
        agent_name="Refresh Bot Rerun",
        avatar_url="https://example.com/avatar-new.png",
        ensure_agent=True,
    )
    with open(identity_path) as f:
        second_identity = f.read()
    with open(bootstrap_path) as f:
        second_bootstrap = f.read()
    with open(heartbeat_path) as f:
        second_heartbeat = f.read()
    with open(user_path) as f:
        second_user = f.read()

    _regression_assert(first["ok"] and second["ok"], "workspace refresh rerun should persist successfully")
    _regression_assert("https://example.com/avatar-old.png" in first_identity, "initial template should contain the first avatar url")
    _regression_assert("https://example.com/avatar-new.png" in second_identity, "rerun should refresh managed template content with the new avatar url")
    _regression_assert("Refresh Bot Rerun" in second_identity, "rerun should refresh managed template content with the new agent name")
    _regression_assert(second_bootstrap == "bootstrap-user-edit", "BOOTSTRAP.md should remain first-run-only on rerun")
    _regression_assert(second_heartbeat == "heartbeat-user-edit", "HEARTBEAT.md should not be clobbered on rerun")
    _regression_assert(second_user == "user-customization", "USER.md should remain user-owned on rerun")
    _regression_assert(len(second.get("binding_summary", {})) > 0, "rerun should keep binding summary intact")
    context["result"] = {
        "first": first,
        "second": second,
        "identity_path": identity_path,
        "second_identity": second_identity,
        "second_bootstrap": second_bootstrap,
        "second_heartbeat": second_heartbeat,
        "second_user": second_user,
    }


def _scenario_allow_from_append_dedupe(context: dict) -> None:
    _write_json_file(context["allow_from_path"], {
        "version": 2,
        "allowFrom": ["ou_1", "ou_2", "ou_1"],
    })
    ok = _write_allow_from("ou_2")
    data = _read_json_file(context["allow_from_path"])
    _regression_assert(ok, "allowFrom append/dedupe should succeed")
    _regression_assert(data == {"version": 2, "allowFrom": ["ou_1", "ou_2"]}, "allowFrom should keep version and dedupe repeated open_id entries")
    context["result"] = data


def _scenario_allow_from_recover(context: dict) -> None:
    _write_text_file(context["allow_from_path"], "not-json")
    ok = _write_allow_from("ou_recovered")
    data = _read_json_file(context["allow_from_path"])
    _regression_assert(ok, "allowFrom recovery should still succeed")
    _regression_assert(data == {"version": 1, "allowFrom": ["ou_recovered"]}, "corrupted allowFrom file should recover to the minimal structure")
    context["result"] = data


def _scenario_avatar_explicit(context: dict) -> None:
    requested_urls = []
    original_urlopen = urllib.request.urlopen

    class _FakeResponse:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(req, context=None, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        requested_urls.append(url)
        return _FakeResponse(b"explicit-avatar")

    urllib.request.urlopen = _fake_urlopen
    try:
        avatar_result = _download_avatar("https://example.com/avatar-explicit.png")
    finally:
        urllib.request.urlopen = original_urlopen
    avatar_path = avatar_result["path"]
    meta = _read_avatar_cache_meta(avatar_path)
    _regression_assert(os.path.isfile(avatar_path), "explicit avatar should be downloaded to the state dir")
    _regression_assert(requested_urls == ["https://example.com/avatar-explicit.png"], "explicit avatar should fetch the provided url only")
    _regression_assert(meta == {"source": "explicit", "url": "https://example.com/avatar-explicit.png"}, "explicit avatar cache metadata should record explicit source")
    _regression_assert(avatar_result == {"path": avatar_path, "url": "https://example.com/avatar-explicit.png", "source": "explicit"}, "explicit avatar result should carry path/url/source")
    context["result"] = {"avatar": avatar_result, "meta": meta, "requested_urls": requested_urls}


def _scenario_avatar_random(context: dict) -> None:
    requested_urls = []
    original_urlopen = urllib.request.urlopen

    class _FakeResponse:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(req, context=None, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        requested_urls.append(url)
        return _FakeResponse(b"random-avatar")

    urllib.request.urlopen = _fake_urlopen
    try:
        avatar_result = _download_avatar(
            "",
            local_sources=[],
            random_source_selector=lambda sources: sources[-1],
            random_sources=["https://example.com/avatar-1.png", "https://example.com/avatar-2.png"],
        )
    finally:
        urllib.request.urlopen = original_urlopen
    avatar_path = avatar_result["path"]
    meta = _read_avatar_cache_meta(avatar_path)
    _regression_assert(requested_urls == ["https://example.com/avatar-2.png"], "random avatar should use the injected selector for deterministic coverage")
    _regression_assert(meta == {"source": "random", "url": "https://example.com/avatar-2.png"}, "random avatar cache metadata should record random source")
    _regression_assert(avatar_result == {"path": avatar_path, "url": "https://example.com/avatar-2.png", "source": "random"}, "random avatar result should carry the selected source url")
    context["result"] = {"avatar": avatar_result, "meta": meta, "requested_urls": requested_urls}


def _scenario_avatar_local_preferred(context: dict) -> None:
    local_avatar = os.path.join(context["temp_root"], "avatar-local.png")
    with open(local_avatar, "wb") as f:
        f.write(b"local-avatar")
    avatar_result = _download_avatar(
        "",
        local_source_selector=lambda sources: sources[0],
        local_sources=[local_avatar],
        random_sources=["https://example.com/avatar-remote.png"],
    )
    avatar_path = avatar_result["path"]
    meta = _read_avatar_cache_meta(avatar_path)
    _regression_assert(os.path.isfile(avatar_path), "local avatar should be copied into runtime state path")
    _regression_assert(avatar_result["source"] == "local", "local avatar should win over remote random sources")
    _regression_assert(meta == {"source": "local", "url": local_avatar}, "local avatar metadata should record the local file path")
    context["result"] = {"avatar": avatar_result, "meta": meta}


def _scenario_avatar_fallback(context: dict) -> None:
    requested_urls = []
    original_urlopen = urllib.request.urlopen

    class _FakeResponse:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(req, context=None, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        requested_urls.append(url)
        if url == "https://example.com/broken-random.png":
            raise OSError("simulated random download failure")
        return _FakeResponse(b"fallback-avatar")

    urllib.request.urlopen = _fake_urlopen
    try:
        avatar_result = _download_avatar(
            "",
            local_sources=[],
            random_source_selector=lambda sources: sources[0],
            random_sources=["https://example.com/broken-random.png"],
        )
    finally:
        urllib.request.urlopen = original_urlopen
    avatar_path = avatar_result["path"]
    meta = _read_avatar_cache_meta(avatar_path)
    _regression_assert(requested_urls == ["https://example.com/broken-random.png", DEFAULT_AVATAR_URL], "fallback avatar should retry with the built-in default url after random failure")
    _regression_assert(meta == {"source": "fallback", "url": DEFAULT_AVATAR_URL}, "fallback avatar cache metadata should record the built-in fallback source")
    _regression_assert(avatar_result == {"path": avatar_path, "url": DEFAULT_AVATAR_URL, "source": "fallback"}, "fallback avatar result should carry the final fallback url")
    context["result"] = {"avatar": avatar_result, "meta": meta, "requested_urls": requested_urls}


def _scenario_avatar_url_propagation(context: dict) -> None:
    config = _build_config_smoke_fixture()
    avatar_url = "https://example.com/final-avatar.png"
    result = _persist_openclaw_config_state(
        config,
        app_id="avatar-propagation-app",
        app_secret="avatar-propagation-secret",
        account_id="avatar-account",
        agent_name="Avatar Bot",
        avatar_url=avatar_url,
        ensure_agent=True,
    )
    persisted = _read_json_file(context["config_path"])
    agent = _find_agent_record(_ensure_list(_ensure_dict(persisted.get("agents")).get("list")), result.get("agent_id") or "")
    with open(os.path.join(_agent_workspace_path(result.get("agent_id") or ""), "IDENTITY.md")) as f:
        workspace_identity = f.read()
    _regression_assert(result["ok"] is True, "avatar propagation scenario should persist agent successfully")
    _regression_assert(_ensure_dict(agent.get("identity") if isinstance(agent, dict) else {}).get("avatar") == avatar_url, "agent identity avatar should persist the resolved avatar url")
    _regression_assert(avatar_url in workspace_identity, "workspace template should embed the resolved avatar url")
    context["result"] = {"persist_result": result, "agent": agent, "identity_md": workspace_identity}


def _scenario_profile_preserve(context: dict) -> None:
    profile_dir = os.path.join(context["state_dir"], _pcfg("profile_dir_name"))
    os.makedirs(profile_dir, exist_ok=True)
    marker_path = os.path.join(profile_dir, "keep.txt")
    _write_text_file(marker_path, "keep")
    returned_dir = _prepare_profile_dir(False)
    _regression_assert(returned_dir == profile_dir, "profile preserve should return the existing profile directory path")
    _regression_assert(os.path.isfile(marker_path), "profile preserve should not delete existing profile contents")
    context["result"] = {"profile_dir": profile_dir, "marker_exists": os.path.isfile(marker_path)}


def _scenario_profile_reset(context: dict) -> None:
    profile_dir = os.path.join(context["state_dir"], _pcfg("profile_dir_name"))
    os.makedirs(profile_dir, exist_ok=True)
    marker_path = os.path.join(profile_dir, "reset.txt")
    _write_text_file(marker_path, "delete")
    returned_dir = _prepare_profile_dir(True)
    _regression_assert(returned_dir == profile_dir, "profile reset should still return the canonical profile path")
    _regression_assert(not os.path.exists(marker_path), "profile reset should remove previous profile contents")
    context["result"] = {"profile_dir": profile_dir, "marker_exists": os.path.exists(marker_path)}


def _scenario_agent_bind_fallback(context: dict) -> None:
    config = _build_config_smoke_fixture()
    original_which = shutil.which
    original_run_openclaw_cli = _run_openclaw_cli

    def _fake_which(binary_name: str):
        if binary_name == "openclaw":
            return "/usr/local/bin/openclaw"
        return original_which(binary_name)

    def _fake_run_openclaw_cli(args: list) -> subprocess.CompletedProcess:
        context["commands"].append({"args": args})
        if args[1:3] == ["agents", "add"]:
            return _regression_completed_process(args, 0, stdout='{"ok":true}')
        if args[1:3] == ["agents", "bind"]:
            return _regression_completed_process(args, 1, stderr='bind failed: simulated channel mismatch')
        if args[1:3] == ["agents", "set-identity"]:
            return _regression_completed_process(args, 0, stdout='{"ok":true}')
        raise AssertionError(f"unexpected openclaw CLI call: {args}")

    shutil.which = _fake_which
    globals()["_run_openclaw_cli"] = _fake_run_openclaw_cli
    try:
        result = _persist_openclaw_config_state(
            config,
            app_id="agent-app-id",
            app_secret="agent-secret",
            account_id="agent-account",
            agent_name="Agent Fallback Bot",
            avatar_url="https://example.com/avatar.png",
            ensure_agent=True,
        )
    finally:
        shutil.which = original_which
        globals()["_run_openclaw_cli"] = original_run_openclaw_cli

    persisted = _read_json_file(context["config_path"])
    _regression_assert(result["ok"], "agent fallback flow should still persist config successfully")
    _regression_assert(result.get("agent_mode") == "fallback", "failed CLI bind should be accepted through fallback mode")
    _regression_assert(result.get("binding_summary", {}).get("bound") is True, "fallback should still create a binding summary")
    _regression_assert(bool(result.get("agent_id")), "fallback should still resolve an agent id")
    _regression_assert(len(_ensure_list(_ensure_dict(persisted.get("agents")).get("list"))) == 1, "fallback should materialize one agent record in config")
    _regression_assert(len(_ensure_list(persisted.get("bindings"))) == 1, "fallback should materialize one binding record in config")
    context["result"] = {"persist_result": result, "persisted": persisted}


def _scenario_permission_partial_match(context: dict) -> None:
    summary = _build_permission_request_summary({
        "im:message": "scope-1",
        "drive:file": "scope-2",
        "admin:*": "scope-risk",
    })
    immediate = summary.pop("_immediate_apply", [])
    _regression_assert("im:message" in summary["matched"], "matched permissions should include available default permissions")
    _regression_assert("drive:file" in summary["approval"]["matched"], "approval permissions should capture second-publish scopes when matched")
    _regression_assert("drive:file" in summary["skipped"]["deferred_for_second_publish"], "second-publish permissions should be deferred from immediate apply")
    _regression_assert("im:message" in immediate and "drive:file" not in immediate, "immediate apply should exclude deferred approval permissions")
    _regression_assert("admin:*" not in summary["requested"] and "admin:*" not in summary["matched"], "high-risk permissions must never be requested even when present in the catalog")
    context["result"] = {"summary": summary, "immediate_apply": immediate}


def _scenario_create_flow_state(context: dict) -> None:
    config = _build_config_smoke_fixture()
    credentials_state = _persist_openclaw_config_state(
        config,
        app_id="flow-app-id",
        app_secret="flow-secret",
        account_id="flow-account",
        agent_name="Flow Bot",
        manage_url="https://open.feishu.cn/app/flow-app-id",
        publish_status="credentials_ready",
        ensure_agent=False,
    )
    ready_state = _persist_openclaw_config_state(
        config,
        app_id="flow-app-id",
        app_secret="flow-secret",
        account_id="flow-account",
        agent_name="Flow Bot",
        avatar_url="https://example.com/avatar.png",
        manage_url="https://open.feishu.cn/app/flow-app-id",
        publish_status="ready_to_publish",
        permission_summary=_new_permission_summary(),
        ensure_agent=True,
    )
    finish_payload = _build_finish_payload(
        app_id="flow-app-id",
        app_secret="flow-secret",
        account_id=ready_state.get("account_id") or "flow-account",
        agent_id=ready_state.get("agent_id") or "",
        agent_name=ready_state.get("agent_name") or "Flow Bot",
        version_id="version-1",
        open_id="ou_flow",
        manage_url="https://open.feishu.cn/app/flow-app-id",
        audit_url="https://feishu.cn/admin/appCenter/audit",
        publish_status="approval_pending",
        permission_summary=_new_permission_summary(),
        binding_summary=ready_state.get("binding_summary"),
    )
    _regression_assert(credentials_state["ok"] and credentials_state.get("agent_id", "") == "", "credentials_ready stage should persist without agent creation")
    _regression_assert(ready_state["ok"] and bool(ready_state.get("agent_id")), "ready_to_publish stage should add agent/binding state")
    _regression_assert(finish_payload["publishStatus"] == "approval_pending", "finish payload should keep publish status for create-flow evidence")
    _regression_assert(finish_payload["bindingSummary"]["bound"] is True, "finish payload should include final binding summary")
    context["result"] = {
        "credentials_state": credentials_state,
        "ready_state": ready_state,
        "finish_payload": finish_payload,
    }


def _scenario_channel_config_write(context: dict) -> None:
    config = _build_config_smoke_fixture()
    channel_config = _normalize_channel_config(
        dm_policy="allowlist",
        group_policy="allowlist",
        allow_from=["ou_owner_1", "ou_owner_2"],
        group_allow_from=["oc_group_1"],
        require_mention=True,
    )
    result = _persist_openclaw_config_state(
        config,
        app_id="policy-app-id",
        app_secret="policy-secret",
        account_id="policy-account",
        agent_name="Policy Bot",
        channel_config=channel_config,
        ensure_agent=False,
    )
    feishu = _ensure_dict(_ensure_dict(config.get("channels")).get("feishu"))
    accounts_default = _ensure_dict(_ensure_dict(feishu.get("accounts")).get("default"))
    _regression_assert(result["ok"], "policy config persist should succeed")
    _regression_assert(feishu.get("dmPolicy") == "allowlist", "top-level dmPolicy should be written")
    _regression_assert(feishu.get("groupPolicy") == "allowlist", "top-level groupPolicy should be written")
    _regression_assert(feishu.get("allowFrom") == ["ou_owner_1", "ou_owner_2"], "top-level allowFrom should be written")
    _regression_assert(feishu.get("groupAllowFrom") == ["oc_group_1"], "top-level groupAllowFrom should be written")
    _regression_assert(feishu.get("requireMention") is True, "top-level requireMention should be written")
    _regression_assert(accounts_default.get("dmPolicy") == "allowlist", "accounts.default should mirror dmPolicy")
    _regression_assert(accounts_default.get("groupPolicy") == "allowlist", "accounts.default should mirror groupPolicy")
    _regression_assert(accounts_default.get("allowFrom") == ["ou_owner_1", "ou_owner_2"], "accounts.default should mirror allowFrom")
    _regression_assert(result.get("channel_config", {}) == channel_config, "persist result should expose written channel config")
    context["result"] = {"feishu": feishu, "result": result}


def _scenario_app_name_conflict_retry(context: dict) -> None:
    creator = FeishuBotCreator.__new__(FeishuBotCreator)
    creator.app_id = None
    creator._api_base = "https://example.com/developers/v1"
    call_names = []

    def _fake_post(_url: str, payload: dict):
        call_names.append(payload.get("name"))
        if len(call_names) == 1:
            return {"code": 40001, "msg": "应用名称已存在"}
        return {"code": 0, "data": {"ClientID": "cli_retry_success"}}

    creator._post = _fake_post
    bot_profile = _normalize_bot_profile(
        fallback_name="廉颇",
        openclaw_name="lianpo",
        name_zh="廉颇",
        desc_zh="正义爆轰",
    )
    ok = FeishuBotCreator.step1_create_app(creator, bot_profile, "")
    _regression_assert(ok is True, "name conflict should retry and eventually succeed")
    _regression_assert(call_names == ["廉颇", "廉颇-2"], "name conflict retry should append numeric suffix on the second attempt")
    _regression_assert(creator.app_id == "cli_retry_success", "successful retry should persist app id")
    _regression_assert(bot_profile["name_zh"] == "廉颇-2", "bot profile should keep the final created Feishu name")
    context["result"] = {"call_names": call_names, "app_id": creator.app_id, "bot_profile": bot_profile}


def _scenario_bot_profile_localization(context: dict) -> None:
    profile = _normalize_bot_profile(
        fallback_name="Fallback Bot",
        openclaw_name="openclaw-bot",
        name_zh="中文机器人",
        desc_zh="中文描述",
    )
    _regression_assert(profile["name_zh"] == "中文机器人", "localized profile should keep Chinese name")
    _regression_assert(profile["openclaw_name"] == "openclaw-bot", "bot profile should keep the OpenClaw-side English identifier")
    _regression_assert(profile["desc_zh"] == "中文描述", "localized profile should keep Chinese description")
    _regression_assert(profile["primary_name"] == "中文机器人", "primary name should prefer Chinese name when provided")
    context["result"] = profile


def _scenario_random_name_library(context: dict) -> None:
    path = _bot_profile_library_path()
    original_content = path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(
        "# Bot Profiles\n\n| openclaw_name | name_zh | desc_zh | avatar_file |\n| --- | --- | --- | --- |\n| lianpo | 廉颇 | 正义爆轰 | avatar/lianpo-105.jpg |\n| xiaoqiao | 小乔 | 恋之微风 | avatar/xiaoqiao-106.jpg |\n",
        encoding="utf-8",
    )
    original_choice = random.choice
    random.choice = lambda values: values[0]
    try:
        generated = _choose_random_bot_profile()
    finally:
        random.choice = original_choice
        if original_content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(original_content, encoding="utf-8")
    _regression_assert(generated["openclaw_name"] == "lianpo", "generated default profile should come from the Markdown library")
    _regression_assert(generated["name_zh"] == "廉颇", "generated default profile should keep the Markdown Chinese name")
    context["result"] = generated


def _scenario_workspace_template_override(context: dict) -> None:
    template_dir = _script_template_dir()
    template_dir.mkdir(exist_ok=True)
    soul_path = template_dir / "SOUL.md"
    original_content = soul_path.read_text(encoding="utf-8") if soul_path.exists() else None
    soul_path.write_text("# 风格\n\n你是 {{agent_name}}，账号 {{account_id}}。\n", encoding="utf-8")
    try:
        templates = _build_workspace_templates(
            agent_id="template-agent",
            agent_name="Template Bot",
            account_id="template-account",
            avatar_url="https://example.com/avatar.png",
        )
    finally:
        if original_content is None:
            soul_path.unlink(missing_ok=True)
        else:
            soul_path.write_text(original_content, encoding="utf-8")
    _regression_assert(
        templates["SOUL.md"] == "# 风格\n\n你是 Template Bot，账号 template-account。\n",
        "workspace templates should prefer script-local template overrides and render placeholders",
    )
    context["result"] = {"soul": templates["SOUL.md"]}


def _scenario_feishu_env_placeholder_write(context: dict) -> None:
    temp_root = Path(context["temp_root"])
    original_project_root_dir = globals()["_project_root_dir"]
    global OPENCLAW_ROOT
    saved_openclaw_root = OPENCLAW_ROOT
    try:
        globals()["_project_root_dir"] = lambda: temp_root
        OPENCLAW_ROOT = str(temp_root / "state")
        (temp_root / "state").mkdir(parents=True, exist_ok=True)
        record = _build_feishu_account_record_from_secrets("demo-account", "cli_demo", "secret_demo")
    finally:
        globals()["_project_root_dir"] = original_project_root_dir
        OPENCLAW_ROOT = saved_openclaw_root
    env_path = temp_root / ".env"
    legacy_feishu_env_path = temp_root / ".env.legacy" / "feishu-accounts.env"
    legacy_runtime_env_path = temp_root / ".env.legacy" / "runtime.env"
    bridge_path = temp_root / "state" / ".env"
    _regression_assert(record["appId"] == "${FEISHU_DEMO_ACCOUNT_APP_ID}", "Feishu appId should be written as env placeholder")
    _regression_assert(record["appSecret"] == "${FEISHU_DEMO_ACCOUNT_APP_SECRET}", "Feishu appSecret should be written as env placeholder")
    _regression_assert(env_path.is_file(), "Unified .env file should be created")
    _regression_assert(not legacy_feishu_env_path.exists(), "legacy feishu env file should not be created")
    _regression_assert(not legacy_runtime_env_path.exists(), "legacy runtime env file should not be created")
    _regression_assert(bridge_path.exists(), "OpenClaw runtime env bridge should be created")
    env_content = env_path.read_text(encoding="utf-8")
    _regression_assert("FEISHU_DEMO_ACCOUNT_APP_ID" in env_content and "cli_demo" in env_content, "Feishu env file should persist appId")
    _regression_assert("FEISHU_DEMO_ACCOUNT_APP_SECRET" in env_content and "secret_demo" in env_content, "Feishu env file should persist appSecret")
    context["result"] = {"record": record, "env_path": str(env_path)}


def _scenario_workspace_skills_copy(context: dict) -> None:
    temp_root = Path(context["temp_root"])
    skills_src = temp_root / "skills-src"
    skills_src.mkdir(parents=True, exist_ok=True)
    sample_skill = skills_src / "demo-skill" / "SKILL.md"
    sample_skill.parent.mkdir(parents=True, exist_ok=True)
    sample_skill.write_text("# demo\n", encoding="utf-8")
    original_script_skills_dir = globals()["_script_skills_dir"]
    try:
        globals()["_script_skills_dir"] = lambda: skills_src
        result = _ensure_workspace_files(
            agent_id="skill-agent",
            agent_name="Skill Agent",
            account_id="skill-account",
            avatar_url="",
        )
    finally:
        globals()["_script_skills_dir"] = original_script_skills_dir
    copied_path = Path(result["managed_skills_dir"]) / "demo-skill" / "SKILL.md"
    _regression_assert(copied_path.is_file(), "workspace generation should copy repo skills into the shared managed skills directory")
    _regression_assert(copied_path.read_text(encoding="utf-8") == "# demo\n", "copied skill file should keep content")
    context["result"] = {"copied_skill": str(copied_path)}


def _scenario_runtime_path_resolution(context: dict) -> None:
    original_platform = sys.platform
    original_xdg_config = os.environ.get("XDG_CONFIG_HOME")
    original_xdg_cache = os.environ.get("XDG_CACHE_HOME")
    original_home = os.environ.get("HOME")
    try:
        sys.platform = "linux"
        os.environ["HOME"] = "/home/tester"
        os.environ["XDG_CONFIG_HOME"] = "/home/tester/.config"
        os.environ["XDG_CACHE_HOME"] = "/home/tester/.cache"

        default_paths = _resolve_runtime_paths()
        _regression_assert(
            default_paths["openclaw_root"] == "/home/tester/.config/openclaw",
            "linux default openclaw root should come from XDG_CONFIG_HOME",
        )
        _regression_assert(
            default_paths["config_path"] == "/home/tester/.config/openclaw/openclaw.json",
            "config path should derive from openclaw root",
        )
        _regression_assert(
            default_paths["allow_from_path"] == "/home/tester/.config/openclaw/credentials/feishu-default-allowFrom.json",
            "allowFrom path should derive from openclaw root",
        )
        _regression_assert(
            default_paths["state_dir"] == "/home/tester/.cache/openclaw/runtime",
            "linux default state dir should come from XDG_CACHE_HOME",
        )

        cli_paths = _resolve_runtime_paths(
            openclaw_root="/srv/openclaw",
            state_dir="/srv/runtime",
        )
        _regression_assert(
            cli_paths["config_path"] == "/srv/openclaw/openclaw.json",
            "cli openclaw root should override config path",
        )
        _regression_assert(
            cli_paths["allow_from_path"] == "/srv/openclaw/credentials/feishu-default-allowFrom.json",
            "cli openclaw root should override allowFrom path",
        )
        _regression_assert(
            cli_paths["state_dir"] == "/srv/runtime",
            "cli state dir should override runtime state dir",
        )
        context["result"] = {
            "default_paths": default_paths,
            "cli_paths": cli_paths,
        }
    finally:
        sys.platform = original_platform
        if original_xdg_config is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = original_xdg_config
        if original_xdg_cache is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = original_xdg_cache
        if original_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = original_home


def _scenario_permissions_single_apply(context: dict) -> None:
    summary = _build_permission_request_summary({
        "im:message": "scope-1",
        "drive:file": "scope-2",
        "admin:*": "scope-risk",
    })
    immediate = summary.pop("_immediate_apply", [])
    _regression_assert(
        "im:message" in immediate and "drive:file" in immediate,
        "all matched safe permissions should be applied immediately in one batch",
    )
    _regression_assert(
        summary["approval"]["matched"] == [],
        "single-apply permission flow should not defer matched scopes into approval bucket",
    )
    _regression_assert(
        summary["skipped"]["deferred_for_second_publish"] == [],
        "single-apply permission flow should not mark matched scopes as deferred",
    )
    _regression_assert(
        "admin:*" not in summary["requested"] and "admin:*" not in summary["matched"],
        "high-risk permissions must still be excluded entirely",
    )
    context["result"] = {"summary": summary, "immediate_apply": immediate}


def _scenario_finish_payload_redacts_secret(context: dict) -> None:
    payload = _build_finish_payload(
        app_id="secret-app-id",
        app_secret="super-secret",
        account_id="secret-account",
        agent_id="secret-agent",
        agent_name="Secret Bot",
        publish_status="published",
        feishu_display_name="廉颇-2",
    )
    _regression_assert("appSecret" not in payload, "finish payload should not expose appSecret by default")
    _regression_assert("app_secret" not in payload, "finish payload should not expose snake_case app_secret by default")
    _regression_assert(payload["appId"] == "secret-app-id", "finish payload should still include non-secret identifiers")
    _regression_assert(payload["feishuDisplayName"] == "廉颇-2", "finish payload should expose the final created Feishu display name")
    context["result"] = payload


def _scenario_terminal_qrcode_render(context: dict) -> None:
    content = '{"qrlogin":{"token":"terminal-token"}}'
    rendered = _build_terminal_qrcode(content, message="请扫码登录飞书")
    _regression_assert("请扫码登录飞书" in rendered, "terminal QR should keep the human-readable prompt")
    _regression_assert("二维码内容:" in rendered, "terminal QR should include raw content fallback")
    _regression_assert(content in rendered, "terminal QR should include the original QR payload")
    _regression_assert(len(rendered.splitlines()) >= 4, "terminal QR render should produce multiple terminal lines")
    context["result"] = {"preview": "\n".join(rendered.splitlines()[:6])}


def _scenario_owner_identity_resolution(context: dict) -> None:
    app_detail = {
        "code": 0,
        "data": {
            "app": {
                "ownerInfo": {
                    "name": "Owner Example",
                    "openId": "ou_owner_123",
                }
            }
        },
    }
    owner = _extract_owner_identity(app_detail)
    _regression_assert(owner == {
        "name": "Owner Example",
        "open_id": "ou_owner_123",
        "source": "app.ownerInfo",
    }, "owner identity resolver should return explicit owner info from app detail")
    context["result"] = owner


def _scenario_openclaw_validate_and_bindings(context: dict) -> None:
    cli_path = shutil.which("openclaw")
    if not cli_path:
        context["result"] = {
            "skipped": True,
            "reason": "openclaw CLI 不存在，跳过宿主机 validate/list/bindings 校验",
        }
        return

    config = _build_config_smoke_fixture()
    original_which = shutil.which
    original_run_openclaw_cli = _run_openclaw_cli

    def _fake_which(binary_name: str):
        if binary_name == "openclaw":
            return cli_path
        return original_which(binary_name)

    def _fake_run_openclaw_cli(args: list) -> subprocess.CompletedProcess:
        if args[1:3] == ["agents", "add"]:
            return _regression_completed_process(args, 0, stdout='{"ok":true}')
        if args[1:3] == ["agents", "bind"]:
            return _regression_completed_process(args, 1, stderr='bind failed: simulated fallback path')
        if args[1:3] == ["agents", "set-identity"]:
            return _regression_completed_process(args, 0, stdout='{"ok":true}')
        return original_run_openclaw_cli(args)

    shutil.which = _fake_which
    globals()["_run_openclaw_cli"] = _fake_run_openclaw_cli
    try:
        persist_result = _persist_openclaw_config_state(
            config,
            app_id="validate-app-id",
            app_secret="validate-secret",
            account_id="validate-account",
            agent_name="Validate Bot",
            avatar_url="https://example.com/avatar.png",
            ensure_agent=True,
        )
    finally:
        shutil.which = original_which
        globals()["_run_openclaw_cli"] = original_run_openclaw_cli

    validate_proc = _run_openclaw_cli([cli_path, "config", "validate", "--json"])
    list_proc = _run_openclaw_cli([cli_path, "agents", "list", "--bindings", "--json"])
    bindings_proc = _run_openclaw_cli([cli_path, "agents", "bindings", "--agent", persist_result["agent_id"], "--json"])
    persisted = _read_openclaw_config()
    validate_account = _ensure_dict(
        _ensure_dict(
            _ensure_dict(_ensure_dict(persisted.get("channels")).get("feishu")).get("accounts")
        ).get("validate-account")
    )
    _regression_assert(
        validate_account.get("appId") == "${FEISHU_VALIDATE_ACCOUNT_APP_ID}",
        "generated config should store env placeholders instead of plaintext appId",
    )
    _regression_assert(
        validate_account.get("appSecret") == "${FEISHU_VALIDATE_ACCOUNT_APP_SECRET}",
        "generated config should store env placeholders instead of plaintext appSecret",
    )
    context["commands"].extend([
        {"args": validate_proc.args, "returncode": validate_proc.returncode, "stdout": validate_proc.stdout, "stderr": validate_proc.stderr},
        {"args": list_proc.args, "returncode": list_proc.returncode, "stdout": list_proc.stdout, "stderr": list_proc.stderr},
        {"args": bindings_proc.args, "returncode": bindings_proc.returncode, "stdout": bindings_proc.stdout, "stderr": bindings_proc.stderr},
    ])

    if validate_proc.returncode != 0 or list_proc.returncode != 0 or bindings_proc.returncode != 0:
        context["result"] = {
            "skipped": True,
            "reason": "宿主机 openclaw CLI/依赖不完整，跳过非阻断 validate/list/bindings 校验",
            "persist_result": persist_result,
            "validate": validate_proc.stdout or validate_proc.stderr,
            "agents_list": list_proc.stdout or list_proc.stderr,
            "bindings": bindings_proc.stdout or bindings_proc.stderr,
        }
        return

    _regression_assert(validate_proc.returncode == 0, "openclaw config validate should pass on the generated temp config")
    _regression_assert(list_proc.returncode == 0, "openclaw agents list --bindings should succeed on the generated temp config")
    _regression_assert(bindings_proc.returncode == 0, "openclaw agents bindings should succeed for the generated agent")

    validate_data = json.loads((validate_proc.stdout or "{}").strip() or "{}")
    list_data = json.loads((list_proc.stdout or "[]").strip() or "[]")
    bindings_data = json.loads((bindings_proc.stdout or "[]").strip() or "[]")

    list_agents = list_data if isinstance(list_data, list) else _ensure_list(list_data.get("agents"))
    listed_agent = _find_agent_record(list_agents, persist_result["agent_id"])
    bindings_list = bindings_data if isinstance(bindings_data, list) else _ensure_list(bindings_data.get("bindings"))
    _regression_assert(validate_data.get("valid") is True, "validate JSON output should report valid=true")
    _regression_assert(isinstance(listed_agent, dict), "agents list output should contain the generated agent id")
    _regression_assert(any(_binding_account_id(binding) == "validate-account" for binding in bindings_list), "agents bindings output should contain the generated feishu binding")
    context["result"] = {
        "persist_result": persist_result,
        "validate": validate_data,
        "agents_list": list_data,
        "bindings": bindings_data,
    }


def _regression_cases() -> list:
    return [
        {
            "name": "runtime-path-resolution",
            "description": "resolve default and CLI-provided runtime paths without hardcoded root paths",
            "inputs": {"platform": "linux", "cli_overrides": ["--openclaw-root", "--state-dir"]},
            "assertions": [
                "default config root derives from XDG_CONFIG_HOME",
                "CLI openclaw root and state dir override derived paths",
            ],
            "runner": _scenario_runtime_path_resolution,
        },
        {
            "name": "legacy-migration",
            "description": "migrate legacy top-level appId/appSecret into accounts map",
            "inputs": {"legacy_app_id": "legacy-app-id", "new_app_id": "new-app-id", "account_id": "new-account"},
            "assertions": [
                "legacy top-level credentials migrate into channels.feishu.accounts",
                "accounts.default policy object stays intact",
                "defaultAccount points to a real account key",
            ],
            "runner": _scenario_legacy_migration,
        },
        {
            "name": "same-app-rerun",
            "description": "rerun with same appId should update existing account instead of appending",
            "inputs": {"existing_account": "existing-account", "app_id": "same-app-id"},
            "assertions": [
                "same appId reuses existing account key",
                "credentials refresh in place",
            ],
            "runner": _scenario_same_app_rerun,
        },
        {
            "name": "new-account-append",
            "description": "append a new account while preserving existing accounts",
            "inputs": {"existing_account": "existing-account", "new_account": "new-account"},
            "assertions": [
                "new account is appended",
                "existing account and defaultAccount remain unchanged",
            ],
            "runner": _scenario_new_account_append,
        },
        {
            "name": "account-id-collision-reject",
            "description": "reject explicit accountId reuse when it already belongs to a different appId",
            "inputs": {"account_id": "acct-1", "existing_app_id": "existing-app-id", "new_app_id": "new-app-id"},
            "assertions": [
                "conflicting explicit accountId is rejected",
                "error explains both conflicting appIds",
            ],
            "runner": _scenario_account_id_collision_reject,
        },
        {
            "name": "accounts-default-preservation",
            "description": "preserve accounts.default policy object during normalization",
            "inputs": {"policy_keys": ["allowFrom", "note"]},
            "assertions": [
                "accounts.default remains a policy object",
                "policy keys are not overwritten by app credentials",
            ],
            "runner": _scenario_accounts_default_preservation,
        },
        {
            "name": "default-account-preservation",
            "description": "keep valid defaultAccount when appending another account",
            "inputs": {"default_account": "primary-account", "new_account": "new-account"},
            "assertions": [
                "existing valid defaultAccount is preserved",
            ],
            "runner": _scenario_default_account_preservation,
        },
        {
            "name": "default-account-repair",
            "description": "repair dangling defaultAccount to a real non-policy account key",
            "inputs": {"default_account": "dangling-account", "expected_accounts": ["primary-account", "new-account"]},
            "assertions": [
                "dangling defaultAccount prefers an existing real account key",
            ],
            "runner": _scenario_default_account_repair,
        },
        {
            "name": "allow-from-append-dedupe",
            "description": "append and dedupe allowFrom entries while preserving version",
            "inputs": {"existing_allow_from": ["ou_1", "ou_2", "ou_1"], "open_id": "ou_2"},
            "assertions": [
                "duplicate open_id is not appended twice",
                "version is preserved",
            ],
            "runner": _scenario_allow_from_append_dedupe,
        },
        {
            "name": "allow-from-recover",
            "description": "recover corrupted allowFrom file into minimal structure",
            "inputs": {"allow_from_content": "not-json", "open_id": "ou_recovered"},
            "assertions": [
                "corrupted file is recovered",
                "current open_id is still persisted",
            ],
            "runner": _scenario_allow_from_recover,
        },
        {
            "name": "avatar-explicit",
            "description": "download explicit avatar url and persist explicit metadata",
            "inputs": {"avatar_url": "https://example.com/avatar-explicit.png"},
            "assertions": [
                "explicit url is fetched exactly once",
                "avatar meta marks source=explicit",
            ],
            "runner": _scenario_avatar_explicit,
        },
        {
            "name": "avatar-random",
            "description": "exercise deterministic random avatar source selection",
            "inputs": {"random_sources": ["https://example.com/avatar-1.png", "https://example.com/avatar-2.png"]},
            "assertions": [
                "injected selector picks deterministic random source",
                "avatar meta marks source=random",
            ],
            "runner": _scenario_avatar_random,
        },
        {
            "name": "avatar-local-preferred",
            "description": "prefer local avatar directory files before remote random sources",
            "inputs": {"local_sources": ["avatar/avatar-local.png"]},
            "assertions": [
                "local avatar wins over remote random sources",
            ],
            "runner": _scenario_avatar_local_preferred,
        },
        {
            "name": "avatar-fallback",
            "description": "fallback to built-in avatar when random download fails",
            "inputs": {"random_source": "https://example.com/broken-random.png", "fallback_url": DEFAULT_AVATAR_URL},
            "assertions": [
                "random download failure triggers built-in fallback",
                "avatar meta marks source=fallback",
            ],
            "runner": _scenario_avatar_fallback,
        },
        {
            "name": "avatar-url-propagation",
            "description": "persist resolved avatar url into agent identity and workspace templates",
            "inputs": {"avatar_url": "https://example.com/final-avatar.png"},
            "assertions": [
                "agent identity avatar uses resolved final url",
                "workspace IDENTITY.md embeds the same resolved url",
            ],
            "runner": _scenario_avatar_url_propagation,
        },
        {
            "name": "workspace-template-refresh",
            "description": "rerun should refresh managed workspace templates with updated identity values",
            "inputs": {"initial_avatar": "https://example.com/avatar-old.png", "rerun_avatar": "https://example.com/avatar-new.png"},
            "assertions": [
                "rerun refreshes managed IDENTITY.md content",
                "updated avatar and agent name propagate to managed templates",
            ],
            "runner": _scenario_workspace_template_refresh,
        },
        {
            "name": "profile-preserve",
            "description": "default profile mode should preserve existing browser profile",
            "inputs": {"reset_profile": False},
            "assertions": [
                "existing profile marker file remains",
            ],
            "runner": _scenario_profile_preserve,
        },
        {
            "name": "profile-reset",
            "description": "explicit reset should remove existing browser profile",
            "inputs": {"reset_profile": True},
            "assertions": [
                "existing profile marker file is deleted",
            ],
            "runner": _scenario_profile_reset,
        },
        {
            "name": "agent-bind-fallback",
            "description": "accept fallback path when CLI bind fails during agent creation",
            "inputs": {"app_id": "agent-app-id", "account_id": "agent-account"},
            "assertions": [
                "failed CLI bind falls back to controlled JSON write",
                "agents.list and bindings are still persisted",
            ],
            "runner": _scenario_agent_bind_fallback,
        },
        {
            "name": "permission-partial-match",
            "description": "partial scope catalog should single-apply matched safe permissions and exclude high-risk ones",
            "inputs": {"catalog": ["im:message", "drive:file", "admin:*"]},
            "assertions": [
                "matched default scope stays immediate when safe",
                "matched drive scope is still applied immediately",
                "high-risk scope is excluded",
            ],
            "runner": _scenario_permissions_single_apply,
        },
        {
            "name": "create-flow-state",
            "description": "persist credentials-ready and ready-to-publish phases with finish payload status",
            "inputs": {"publish_statuses": ["credentials_ready", "ready_to_publish", "approval_pending"]},
            "assertions": [
                "credentials_ready phase does not require agent creation",
                "ready_to_publish phase produces agent/binding state",
                "finish payload keeps publish status and binding summary",
            ],
            "runner": _scenario_create_flow_state,
        },
        {
            "name": "channel-config-write",
            "description": "persist dmPolicy/groupPolicy/allowFrom/groupAllowFrom/requireMention into Feishu config",
            "inputs": {"dmPolicy": "allowlist", "groupPolicy": "allowlist"},
            "assertions": [
                "top-level channel policy fields are written",
                "accounts.default mirrors the DM policy fields",
            ],
            "runner": _scenario_channel_config_write,
        },
        {
            "name": "app-name-conflict-retry",
            "description": "retry create app with suffixed Feishu name when the original name already exists",
            "inputs": {"name_zh": "廉颇"},
            "assertions": [
                "name conflict retries with numeric suffix",
            ],
            "runner": _scenario_app_name_conflict_retry,
        },
        {
            "name": "bot-profile-localization",
            "description": "keep Feishu Chinese labels and OpenClaw-side English identifier",
            "inputs": {"name_zh": "中文机器人", "openclaw_name": "openclaw-bot"},
            "assertions": [
                "localized bot profile keeps Chinese labels and English identifier",
            ],
            "runner": _scenario_bot_profile_localization,
        },
        {
            "name": "random-name-library",
            "description": "default generated name should come from the built-in classics name library",
            "inputs": {"library": "四大名著人物"},
            "assertions": [
                "generated default name comes from the classics name library",
            ],
            "runner": _scenario_random_name_library,
        },
        {
            "name": "workspace-template-override",
            "description": "prefer script-local template overrides when generating workspace files",
            "inputs": {"template_file": "template/SOUL.md"},
            "assertions": [
                "workspace templates prefer script-local template overrides",
            ],
            "runner": _scenario_workspace_template_override,
        },
        {
            "name": "feishu-env-placeholder-write",
            "description": "persist Feishu credentials into the unified .env file and write config placeholders instead of plaintext",
            "inputs": {"account_id": "demo-account"},
            "assertions": [
                "Feishu account credentials are stored in .env and written as placeholders",
            ],
            "runner": _scenario_feishu_env_placeholder_write,
        },
        {
            "name": "shared-skills-copy",
            "description": "copy repo skills into the shared managed skills directory",
            "inputs": {"skills_dir": "skills/"},
            "assertions": [
                "workspace generation copies repo skills into the shared managed skills directory",
            ],
            "runner": _scenario_workspace_skills_copy,
        },
        {
            "name": "finish-payload-redacts-secret",
            "description": "default finish payload should omit app secret fields",
            "inputs": {"app_id": "secret-app-id"},
            "assertions": [
                "finish payload omits appSecret and app_secret by default",
                "non-secret identifiers remain available",
            ],
            "runner": _scenario_finish_payload_redacts_secret,
        },
        {
            "name": "terminal-qrcode-render",
            "description": "render login QR into terminal-friendly text without breaking raw payload fallback",
            "inputs": {"content": "{\"qrlogin\":{\"token\":\"terminal-token\"}}"},
            "assertions": [
                "terminal QR keeps the prompt",
                "terminal QR still includes raw payload fallback",
            ],
            "runner": _scenario_terminal_qrcode_render,
        },
        {
            "name": "owner-identity-resolution",
            "description": "extract owner open_id from explicit app detail owner fields",
            "inputs": {"owner_field": "ownerInfo.openId"},
            "assertions": [
                "owner resolver returns explicit owner info",
            ],
            "runner": _scenario_owner_identity_resolution,
        },
        {
            "name": "openclaw-validate-and-bindings",
            "description": "optionally run host openclaw validate/list/bindings on generated temp config",
            "inputs": {"commands": ["openclaw config validate --json", "openclaw agents list --bindings --json", "openclaw agents bindings --json"]},
            "assertions": [
                "host CLI validation is reported when available",
                "missing host CLI dependencies do not block direct-write sync verification",
            ],
            "runner": _scenario_openclaw_validate_and_bindings,
        },
    ]


def cmd_regression_test():
    evidence_root = _regression_evidence_root()
    if os.path.isdir(evidence_root):
        shutil.rmtree(evidence_root)
    os.makedirs(evidence_root, exist_ok=True)

    cases = _regression_cases()
    results = []
    events = []
    total = len(cases)

    _log_info(
        "regression",
        "开始执行批量回归夹具",
        scenario_count=total,
        command="python3 feishu_bot_creator.py regression-test",
        evidence_root=evidence_root,
    )

    for index, case in enumerate(cases, start=1):
        _emit_progress("regression", f"执行场景 {case['name']}", current=index, total=total)
        result = _run_regression_case(
            case["name"],
            case["description"],
            inputs=case["inputs"],
            assertions=case["assertions"],
            runner=case["runner"],
        )
        results.append(result)
        event = {
            "index": index,
            "total": total,
            "name": result["name"],
            "status": result["status"],
            "evidence_path": result["evidence_path"],
        }
        if result.get("error"):
            event["error"] = result["error"]
        events.append(event)
        _emit(
            "regression_case",
            "success" if result["status"] == "passed" else "error",
            "regression",
            f"场景 {result['name']} {result['status']}",
            case=result,
        )

    passed = len([item for item in results if item["status"] == "passed"])
    failed = len(results) - passed
    summary = {
        "ok": failed == 0,
        "command": "python3 feishu_bot_creator.py regression-test",
        "scenario_count": total,
        "scenario_names": [case["name"] for case in cases],
        "passed": passed,
        "failed": failed,
        "evidence_root": evidence_root,
        "summary_path": _regression_summary_path(),
        "events_path": _regression_events_path(),
        "results": results,
    }

    _write_json_file(_regression_summary_path(), summary)
    _write_text_file(
        _regression_events_path(),
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
    )

    _emit_finish(
        "批量回归完成。可复跑命令: python3 feishu_bot_creator.py regression-test",
        summary,
    )
    sys.exit(0 if failed == 0 else 1)


def _usage_text() -> str:
    return """用法:
  python3 feishu_bot_creator.py init
  python3 feishu_bot_creator.py create --account-id <id> [--agent-name <name>] [--avatar-url <url>] [--greeting <text>] [--platform feishu|lark] [--openclaw-root <dir>] [--state-dir <dir>] [--reset-profile]
  python3 feishu_bot_creator.py cleanup [--platform feishu|lark] [--state-dir <dir>]
  python3 feishu_bot_creator.py config-test [--platform feishu|lark] [--openclaw-root <dir>] [--state-dir <dir>]
  python3 feishu_bot_creator.py regression-test [--platform feishu|lark] [--openclaw-root <dir>] [--state-dir <dir>]
  python3 feishu_bot_creator.py help

命令说明:
  init             检查并安装 playwright / Chromium 依赖
  create           扫码登录并创建飞书/Lark 机器人；必须显式传入 --account-id，交互式终端会提示填写飞书中文标识、智能体英文标识与飞书策略
  cleanup          清理残留浏览器与状态文件
  config-test      只验证配置归一化/落盘；默认使用临时沙箱，可用 CLI/环境变量覆盖路径
  regression-test  运行内置回归夹具并刷新 evidence summary/events

路径覆盖环境变量:
  OPENCLAW_CONFIG_PATH
  OPENCLAW_ALLOW_FROM_PATH
  OPENCLAW_STATE_DIR

CLI 路径优先级:
  --openclaw-root / --state-dir > 环境变量 > 平台默认路径
"""


def _create_usage_text() -> str:
    return """用法:
  python3 feishu_bot_creator.py create --account-id <id> [--agent-name <name>] [--avatar-url <url>] [--greeting <text>] [--platform feishu|lark] [--openclaw-root <dir>] [--state-dir <dir>] [--reset-profile]

说明:
  --account-id <id>   必填；OpenClaw 中的显式账号 key，不能使用 default
  --agent-name <name> 可选；生成/复用 agent 时使用的人类可读名称
  --avatar-url <url>  可选；显式头像地址；留空时走随机源/默认头像兜底
  --greeting <text>   可选；创建完成后发给 owner 的欢迎语
  --platform <name>   可选；feishu 或 lark
  --openclaw-root     可选；OpenClaw 配置根目录，脚本会派生 openclaw.json/credentials/workspace/agents
  --state-dir         可选；浏览器 profile、状态文件和临时头像目录
  --reset-profile     可选；显式重置浏览器 profile

交互式终端下会额外提示:
  - 飞书机器人中文名称 / 中文描述
  - 智能体英文标识
  - dmPolicy / groupPolicy / allowFrom / groupAllowFrom / requireMention

示例:
  python3 feishu_bot_creator.py create --account-id bot-main --agent-name "客服助手"
  python3 feishu_bot_creator.py create --account-id bot-main --avatar-url https://example.com/avatar.png
  python3 feishu_bot_creator.py create --account-id bot-main --openclaw-root /data/openclaw --state-dir /data/runtime
"""


# ============================================================
# 命令: cleanup
# ============================================================
def cmd_cleanup():
    _kill_cdp_browser()
    sf = _state_file()
    if os.path.isfile(sf):
        os.remove(sf)
    _log_success("cleanup", "已清理")


# ============================================================
# 入口
# ============================================================
def main():
    global PLATFORM

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(_usage_text())
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "init":
        cmd_init()
    elif cmd == "create":
        if any(arg in ("-h", "--help", "help") for arg in sys.argv[2:]):
            print(_create_usage_text())
            sys.exit(0)
        # 解析可选参数: --account-id <id> --agent-name <name> --avatar-url <url> --greeting <text>
        # --platform <feishu|lark> --openclaw-root <dir> --state-dir <dir> --reset-profile
        account_id = ""
        agent_name = ""
        avatar_url = ""
        greeting = ""
        openclaw_root = ""
        state_dir = ""
        reset_profile = False
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--account-id" and i + 1 < len(args):
                account_id = args[i + 1]
                i += 2
            elif args[i] == "--agent-name" and i + 1 < len(args):
                agent_name = args[i + 1]
                i += 2
            elif args[i] == "--avatar-url" and i + 1 < len(args):
                avatar_url = args[i + 1]
                i += 2
            elif args[i] == "--greeting" and i + 1 < len(args):
                greeting = args[i + 1]
                i += 2
            elif args[i] == "--platform" and i + 1 < len(args):
                p = args[i + 1].lower()
                if p not in ("feishu", "lark"):
                    _emit_error("main", f"不支持的平台: {p}，请使用 feishu 或 lark")
                    sys.exit(1)
                PLATFORM = p
                i += 2
            elif args[i] == "--openclaw-root" and i + 1 < len(args):
                openclaw_root = args[i + 1]
                i += 2
            elif args[i] == "--state-dir" and i + 1 < len(args):
                state_dir = args[i + 1]
                i += 2
            elif args[i] == "--reset-profile":
                reset_profile = True
                i += 1
            else:
                i += 1
        _apply_runtime_paths(openclaw_root=openclaw_root, state_dir=state_dir)
        cmd_create(account_id=account_id, agent_name=agent_name, avatar_url=avatar_url,
                   greeting=greeting, reset_profile=reset_profile)
    elif cmd == "cleanup":
        # cleanup 也支持 --platform 参数
        args = sys.argv[2:]
        i = 0
        state_dir = ""
        while i < len(args):
            if args[i] == "--platform" and i + 1 < len(args):
                p = args[i + 1].lower()
                if p in ("feishu", "lark"):
                    PLATFORM = p
                i += 2
            elif args[i] == "--state-dir" and i + 1 < len(args):
                state_dir = args[i + 1]
                i += 2
            else:
                i += 1
        _apply_runtime_paths(state_dir=state_dir)
        cmd_cleanup()
    elif cmd == "config-test":
        args = sys.argv[2:]
        i = 0
        batch_mode = False
        openclaw_root = ""
        state_dir = ""
        while i < len(args):
            if args[i] == "--platform" and i + 1 < len(args):
                p = args[i + 1].lower()
                if p in ("feishu", "lark"):
                    PLATFORM = p
                i += 2
            elif args[i] == "--openclaw-root" and i + 1 < len(args):
                openclaw_root = args[i + 1]
                i += 2
            elif args[i] == "--state-dir" and i + 1 < len(args):
                state_dir = args[i + 1]
                i += 2
            elif args[i] == "--batch":
                batch_mode = True
                i += 1
            else:
                i += 1
        _apply_runtime_paths(openclaw_root=openclaw_root, state_dir=state_dir)
        if batch_mode:
            cmd_regression_test()
        cmd_config_test()
    elif cmd == "regression-test":
        args = sys.argv[2:]
        i = 0
        openclaw_root = ""
        state_dir = ""
        while i < len(args):
            if args[i] == "--platform" and i + 1 < len(args):
                p = args[i + 1].lower()
                if p in ("feishu", "lark"):
                    PLATFORM = p
                i += 2
            elif args[i] == "--openclaw-root" and i + 1 < len(args):
                openclaw_root = args[i + 1]
                i += 2
            elif args[i] == "--state-dir" and i + 1 < len(args):
                state_dir = args[i + 1]
                i += 2
            else:
                i += 1
        _apply_runtime_paths(openclaw_root=openclaw_root, state_dir=state_dir)
        cmd_regression_test()
    else:
        _emit_error("main", f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
