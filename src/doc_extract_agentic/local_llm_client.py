from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)

_SDK_CALL_TIMEOUT_SECONDS = 90
_SDK_MAX_RETRIES = 2


@dataclass
class LocalLLMConfig:
    enabled: bool
    provider: str
    endpoint: str
    model: str
    api_key: str
    timeout_seconds: int
    temperature: float
    app_name: str
    auto_download_model: bool


class LocalLLMClient:
    def __init__(self, cfg: LocalLLMConfig) -> None:
        self.cfg = cfg

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LocalLLMClient":
        llm_cfg = config.get("local_llm", {})
        cfg = LocalLLMConfig(
            enabled=bool(llm_cfg.get("enabled", True)),
            provider=str(llm_cfg.get("provider", "foundry_local_sdk")),
            endpoint=str(llm_cfg.get("endpoint", "http://localhost:5764/v1")),
            model=str(llm_cfg.get("model", "phi-4")),
            api_key=str(llm_cfg.get("api_key", "")),
            timeout_seconds=int(llm_cfg.get("timeout_seconds", 120)),
            temperature=float(llm_cfg.get("temperature", 0.0)),
            app_name=str(llm_cfg.get("app_name", "doc-extract-agentic")),
            auto_download_model=bool(llm_cfg.get("auto_download_model", True)),
        )
        return cls(cfg)

    def is_ready(self) -> bool:
        if not self.cfg.enabled or not self.cfg.model:
            return False
        if self.cfg.provider == "openai_compatible":
            return bool(self.cfg.endpoint)
        if self.cfg.provider == "foundry_local_sdk":
            return True
        return False

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
        if not self.is_ready():
            return None

        if self.cfg.provider == "foundry_local_sdk":
            raw_text = self._chat_completion_foundry_sdk(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        else:
            raw_text = self._chat_completion_openai_compatible(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

        if not raw_text:
            return None

        logger.debug("LLM raw response: %s", raw_text[:500])
        parsed = _extract_json_object(raw_text)
        if not parsed:
            # Truncate for readability
            preview = raw_text[:300].replace("\n", " ")
            print(f"  [LLM] Could not parse JSON from response: {preview!r}")
        return parsed

    def _chat_completion_openai_compatible(
        self, system_prompt: str, user_prompt: str
    ) -> str:
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.cfg.temperature,
        }

        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"

        endpoint = self.cfg.endpoint.rstrip("/") + "/chat/completions"
        req = request.Request(
            endpoint,
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )

        try:
            with request.urlopen(req, timeout=self.cfg.timeout_seconds) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return (
                    body.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
        except (
            HTTPError,
            URLError,
            OSError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            logger.warning("Local LLM call failed: %s", exc)
            return ""

    def _chat_completion_foundry_sdk(self, system_prompt: str, user_prompt: str) -> str:
        try:
            from foundry_local_sdk import Configuration, FoundryLocalManager
        except ModuleNotFoundError:
            logger.warning(
                "foundry_local_sdk not installed. Install foundry-local-sdk-winml."
            )
            return ""

        try:
            # FoundryLocalManager is process-wide singleton; re-initialize attempts
            # can occur in iterative loops and should not fail chat calls.
            try:
                FoundryLocalManager.initialize(
                    Configuration(app_name=self.cfg.app_name)
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if "singleton" not in str(exc).lower():
                    raise

            manager = FoundryLocalManager.instance
            model = manager.catalog.get_model(self.cfg.model)
            if model is None:
                logger.warning(
                    "Foundry Local model alias not found: %s", self.cfg.model
                )
                return ""

            # Some app_name contexts can default to a non-cached variant.
            # Prefer a cached variant when available to avoid path/load failures.
            try:
                variants = list(getattr(model, "variants", []) or [])
                selected_id = str(getattr(model, "id", ""))
                selected_cached = any(
                    str(getattr(v, "id", "")) == selected_id
                    and bool(getattr(v, "is_cached", False))
                    for v in variants
                )
                if (
                    variants
                    and not selected_cached
                    and hasattr(model, "select_variant")
                ):
                    cached_variant = next(
                        (v for v in variants if bool(getattr(v, "is_cached", False))),
                        None,
                    )
                    if cached_variant is not None:
                        model.select_variant(cached_variant)
                        logger.info(
                            "Selected cached Foundry variant: %s",
                            getattr(cached_variant, "id", "unknown"),
                        )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("Foundry variant selection fallback failed: %s", exc)

            if self.cfg.auto_download_model:
                is_cached = True
                if hasattr(model, "is_cached"):
                    try:
                        is_cached = bool(model.is_cached())
                    except Exception:  # pylint: disable=broad-exception-caught
                        is_cached = True
                if not is_cached and hasattr(model, "download"):
                    model.download(lambda _pct: None)

            if hasattr(model, "load"):
                try:
                    model.load()
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    # If a GPU variant requires WebGPU in this runtime, retry with
                    # a cached CPU variant when available.
                    if "webgpu" in str(exc).lower() and hasattr(
                        model, "select_variant"
                    ):
                        variants = list(getattr(model, "variants", []) or [])
                        cpu_cached_variant = next(
                            (
                                v
                                for v in variants
                                if bool(getattr(v, "is_cached", False))
                                and "cpu" in str(getattr(v, "id", "")).lower()
                            ),
                            None,
                        )
                        if cpu_cached_variant is not None:
                            model.select_variant(cpu_cached_variant)
                            logger.info(
                                "Retrying with cached CPU Foundry variant: %s",
                                getattr(cpu_cached_variant, "id", "unknown"),
                            )
                            model.load()
                        else:
                            raise
                    else:
                        raise

            chat_client = model.get_chat_client()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            # Wrap complete_chat in a thread so we can apply a hard timeout.
            # The Foundry SDK can hang indefinitely on cancellation/load errors.
            last_exc: Exception | None = None
            for attempt in range(1, _SDK_MAX_RETRIES + 1):
                try:
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(chat_client.complete_chat, messages)
                        try:
                            response = future.result(timeout=_SDK_CALL_TIMEOUT_SECONDS)
                        except FuturesTimeoutError:
                            logger.warning(
                                "Foundry SDK chat timed out after %ds (attempt %d/%d)",
                                _SDK_CALL_TIMEOUT_SECONDS,
                                attempt,
                                _SDK_MAX_RETRIES,
                            )
                            future.cancel()
                            if attempt < _SDK_MAX_RETRIES:
                                time.sleep(2)
                            continue

                    choices = _read_attr_or_key(response, "choices", default=[])
                    if not choices:
                        return ""
                    first = choices[0]
                    message = _read_attr_or_key(first, "message", default={})
                    content = _read_attr_or_key(message, "content", default="")
                    return str(content).strip()

                except Exception as exc:  # pylint: disable=broad-exception-caught
                    last_exc = exc
                    logger.warning(
                        "Foundry Local SDK call failed (attempt %d/%d): %s",
                        attempt,
                        _SDK_MAX_RETRIES,
                        exc,
                    )
                    if attempt < _SDK_MAX_RETRIES:
                        time.sleep(2)

            if last_exc:
                logger.warning("All Foundry SDK attempts exhausted: %s", last_exc)
            return ""
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Foundry Local SDK setup failed: %s", exc)
            return ""


def _read_attr_or_key(obj: Any, name: str, default: Any) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None

    # Direct parse first.
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Try fenced code block payloads.
    if "```" in stripped:
        parts = stripped.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

    # Last attempt: parse from first '{' to last '}'.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        candidate = stripped[start : end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None

    return None
