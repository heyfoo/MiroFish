"""
OASIS 模拟运行时调优（低配机器 / 本地 LLM 友好）

这个模块集中管理模拟子进程中与"资源消耗"直接相关的几个开关，
三个模拟脚本（parallel / twitter / reddit）都通过它来创建 OASIS 环境：

1. Twitter 推荐系统类型（OASIS_TWITTER_RECSYS）
   OASIS 的 ``DefaultPlatformType.TWITTER`` 固定使用 ``twhin-bert`` 推荐系统，
   首次刷新推荐表时会从 HuggingFace 下载 ``Twitter/twhin-bert-base``（约 1GB），
   并用 PyTorch 在 CPU 上为所有用户与帖子做向量编码。
   在 8GB 内存的机器上这是导致模拟卡顿、内存溢出乃至崩溃的主要原因，
   而且在无法访问 HuggingFace 的网络环境下会直接失败。
   默认改为 ``random``（OASIS 官方支持的纯 Python 推荐策略，不加载任何模型）。

2. LLM 并发上限（LLM_MAX_CONCURRENCY）
   OASIS 每个平台环境用一个信号量限制同时进行的 LLM 请求数。
   云端 API 可以承受 30 并发，但本地 LLM（Ollama / LM Studio / vLLM 单卡）
   通常只能同时处理 1~4 个请求，30 并发只会排队直到超时。
   未显式配置时，如果检测到 LLM 地址是本机地址，会自动降到较低的并发数。

3. 模型请求超时（MODEL_TIMEOUT）
   camel-ai 默认 180 秒。本地小模型在 CPU 上生成一条回复可能更久，
   对本地 LLM 自动放宽到 600 秒（用户显式设置时不覆盖）。

所有 OASIS 相关的 import 都放在函数内部，便于在没有安装 camel-oasis 的环境中
对纯逻辑部分进行单元测试。
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

# 与 OASIS 原有 DefaultPlatformType.TWITTER 保持一致的平台参数
TWITTER_PLATFORM_KWARGS = {
    "refresh_rec_post_count": 2,
    "max_rec_post_len": 2,
    "following_post_count": 3,
}

# OASIS 支持的 Twitter 推荐系统类型（见 oasis.social_platform.typing.RecsysType）
#   random     - 纯随机推荐，不加载任何模型（默认，最省资源）
#   twitter    - 基于 paraphrase-MiniLM-L6-v2 的个性化推荐（约 90MB 模型）
#   twhin-bert - 基于 Twitter/twhin-bert-base 的个性化推荐（约 1GB 模型，OASIS 原始默认）
TWITTER_RECSYS_CHOICES = ("random", "twitter", "twhin-bert")
DEFAULT_TWITTER_RECSYS = "random"

DEFAULT_LLM_CONCURRENCY = 30
LOCAL_LLM_DEFAULT_CONCURRENCY = 2
LOCAL_LLM_DEFAULT_TIMEOUT_SECONDS = 600

LOCAL_HOSTNAMES = frozenset({
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "host.docker.internal",
})


def is_local_llm_url(base_url: Optional[str]) -> bool:
    """判断 LLM base_url 是否指向本机（Ollama / LM Studio 等本地推理服务）。"""
    if not base_url:
        return False
    candidate = base_url.strip()
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    try:
        hostname = urlparse(candidate).hostname
    except ValueError:
        return False
    if not hostname:
        return False
    hostname = hostname.lower()
    return hostname in LOCAL_HOSTNAMES or hostname.endswith(".local")


def _read_positive_int(env: Mapping[str, str], key: str) -> Optional[int]:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return None
    try:
        value = int(str(raw).strip())
    except ValueError:
        print(f"警告: 环境变量 {key}={raw!r} 不是整数，已忽略")
        return None
    if value <= 0:
        print(f"警告: 环境变量 {key}={raw!r} 必须大于 0，已忽略")
        return None
    return value


def get_llm_concurrency(
    base_url: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    """
    返回单个平台环境允许的最大并发 LLM 请求数。

    优先级：LLM_MAX_CONCURRENCY 环境变量 > 本地 LLM 自动降级 > 默认 30。
    """
    env = os.environ if env is None else env
    configured = _read_positive_int(env, "LLM_MAX_CONCURRENCY")
    if configured is not None:
        return configured
    if is_local_llm_url(base_url):
        return LOCAL_LLM_DEFAULT_CONCURRENCY
    return DEFAULT_LLM_CONCURRENCY


def get_twitter_recsys_type(env: Optional[Mapping[str, str]] = None) -> str:
    """返回 Twitter 平台使用的推荐系统类型（非法值回退到默认值并给出警告）。"""
    env = os.environ if env is None else env
    raw = (env.get("OASIS_TWITTER_RECSYS") or "").strip().lower()
    if not raw:
        return DEFAULT_TWITTER_RECSYS
    if raw in TWITTER_RECSYS_CHOICES:
        return raw
    print(
        f"警告: OASIS_TWITTER_RECSYS={raw!r} 无效，"
        f"可选值: {', '.join(TWITTER_RECSYS_CHOICES)}，已回退到 {DEFAULT_TWITTER_RECSYS}"
    )
    return DEFAULT_TWITTER_RECSYS


def apply_local_llm_defaults(base_url: Optional[str], env: Optional[Any] = None) -> bool:
    """
    针对本地 LLM 放宽 camel-ai 的请求超时（MODEL_TIMEOUT）。

    只在用户没有显式设置时生效。返回是否应用了本地默认值。
    """
    env = os.environ if env is None else env
    if not is_local_llm_url(base_url):
        return False
    if (env.get("MODEL_TIMEOUT") or "").strip():
        return False
    env["MODEL_TIMEOUT"] = str(LOCAL_LLM_DEFAULT_TIMEOUT_SECONDS)
    return True


def describe_runtime(
    base_url: Optional[str] = None,
    platform: str = "",
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """生成一行可读的运行时配置摘要，用于模拟日志。"""
    env = os.environ if env is None else env
    parts = [f"llm_concurrency={get_llm_concurrency(base_url, env)}"]
    if is_local_llm_url(base_url):
        parts.append("local_llm=yes")
    if platform == "twitter":
        parts.append(f"twitter_recsys={get_twitter_recsys_type(env)}")
    timeout = env.get("MODEL_TIMEOUT")
    if timeout:
        parts.append(f"model_timeout={timeout}s")
    return ", ".join(parts)


def make_twitter_env(agent_graph, db_path: str, semaphore: int):
    """
    创建 Twitter 模拟环境。

    默认使用轻量推荐系统；只有显式设置 ``OASIS_TWITTER_RECSYS=twhin-bert`` 时
    才走 OASIS 原始的 ``DefaultPlatformType.TWITTER``。
    """
    import oasis

    recsys_type = get_twitter_recsys_type()
    if recsys_type == "twhin-bert":
        return oasis.make(
            agent_graph=agent_graph,
            platform=oasis.DefaultPlatformType.TWITTER,
            database_path=db_path,
            semaphore=semaphore,
        )

    from oasis import Platform
    from oasis.social_platform.channel import Channel

    platform = Platform(
        db_path=db_path,
        channel=Channel(),
        recsys_type=recsys_type,
        **TWITTER_PLATFORM_KWARGS,
    )
    return oasis.make(
        agent_graph=agent_graph,
        platform=platform,
        database_path=db_path,
        semaphore=semaphore,
    )


def make_reddit_env(agent_graph, db_path: str, semaphore: int):
    """创建 Reddit 模拟环境（Reddit 推荐系统本身不依赖模型，仅统一并发配置）。"""
    import oasis

    return oasis.make(
        agent_graph=agent_graph,
        platform=oasis.DefaultPlatformType.REDDIT,
        database_path=db_path,
        semaphore=semaphore,
    )
