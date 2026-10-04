"""低配运行时开关：不依赖 camel-oasis，只验证纯配置逻辑。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from simulation_runtime import (  # noqa: E402
    DEFAULT_LLM_CONCURRENCY,
    DEFAULT_TWITTER_RECSYS,
    LOCAL_LLM_DEFAULT_CONCURRENCY,
    LOCAL_LLM_DEFAULT_TIMEOUT_SECONDS,
    apply_local_llm_defaults,
    describe_runtime,
    get_llm_concurrency,
    get_twitter_recsys_type,
    is_local_llm_url,
)


class TestLocalLlmDetection:
    @pytest.mark.parametrize("url", [
        "http://127.0.0.1:11434/v1",
        "http://localhost:11434/v1",
        "http://host.docker.internal:1234/v1",
        "localhost:11434",
        "http://ollama.local/v1",
    ])
    def test_local_addresses(self, url):
        assert is_local_llm_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://api.openai.com/v1",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "",
        None,
        "not a url",
    ])
    def test_remote_or_empty_addresses(self, url):
        assert is_local_llm_url(url) is False


class TestLlmConcurrency:
    def test_cloud_default_when_unset(self):
        assert get_llm_concurrency("https://api.openai.com/v1", env={}) == DEFAULT_LLM_CONCURRENCY

    def test_local_default_when_unset(self):
        assert get_llm_concurrency(
            "http://127.0.0.1:11434/v1", env={}
        ) == LOCAL_LLM_DEFAULT_CONCURRENCY

    def test_explicit_value_overrides_local_default(self):
        env = {"LLM_MAX_CONCURRENCY": "4"}
        assert get_llm_concurrency("http://127.0.0.1:11434/v1", env=env) == 4

    @pytest.mark.parametrize("raw", ["0", "-3", "abc", "  "])
    def test_invalid_values_are_ignored(self, raw):
        env = {"LLM_MAX_CONCURRENCY": raw}
        assert get_llm_concurrency("https://api.openai.com/v1", env=env) == DEFAULT_LLM_CONCURRENCY


class TestTwitterRecsys:
    def test_defaults_to_lightweight_recommender(self):
        assert get_twitter_recsys_type(env={}) == DEFAULT_TWITTER_RECSYS
        assert DEFAULT_TWITTER_RECSYS == "random"

    @pytest.mark.parametrize("choice", ["random", "twitter", "twhin-bert"])
    def test_accepts_known_choices(self, choice):
        assert get_twitter_recsys_type(env={"OASIS_TWITTER_RECSYS": choice}) == choice

    def test_rejects_unknown_choice(self):
        assert get_twitter_recsys_type(env={"OASIS_TWITTER_RECSYS": "gpu-bert"}) == "random"

    def test_choice_is_case_insensitive(self):
        assert get_twitter_recsys_type(env={"OASIS_TWITTER_RECSYS": "TWHIN-BERT"}) == "twhin-bert"


class TestLocalTimeout:
    def test_sets_timeout_only_for_local_llm(self):
        env = {}
        assert apply_local_llm_defaults("http://localhost:11434/v1", env) is True
        assert env["MODEL_TIMEOUT"] == str(LOCAL_LLM_DEFAULT_TIMEOUT_SECONDS)

    def test_does_not_override_an_explicit_timeout(self):
        env = {"MODEL_TIMEOUT": "90"}
        assert apply_local_llm_defaults("http://localhost:11434/v1", env) is False
        assert env["MODEL_TIMEOUT"] == "90"

    def test_leaves_cloud_endpoints_alone(self):
        env = {}
        assert apply_local_llm_defaults("https://api.openai.com/v1", env) is False
        assert "MODEL_TIMEOUT" not in env


def test_runtime_summary_mentions_the_active_knobs():
    summary = describe_runtime(
        "http://127.0.0.1:11434/v1",
        platform="twitter",
        env={"MODEL_TIMEOUT": "600"},
    )
    assert "llm_concurrency=2" in summary
    assert "local_llm=yes" in summary
    assert "twitter_recsys=random" in summary
    assert "model_timeout=600s" in summary
