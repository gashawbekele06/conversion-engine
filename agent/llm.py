"""LLM wrapper.

Routes through OpenRouter (dev tier) or Claude/OpenAI (eval tier) when
keys are present; otherwise falls back to a deterministic template
renderer so the agent still produces grounded outbound copy for the
interim end-to-end demo.

The interim fallback is NOT a graded output — it exists so the pipeline
is runnable without external credentials.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from .config import Config, load_config
from .tracing import get_tracer


@dataclass
class LLMResponse:
    text: str
    model: str
    usd_cost: float
    latency_ms: float
    input_tokens: int
    output_tokens: int
    fallback_used: bool


class LLM:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()

    def generate(self, *, system: str, user: str, temperature: float = 0.3,
                 max_tokens: int = 400) -> LLMResponse:
        tracer = get_tracer()
        with tracer.trace("llm.generate", model=self.config.llm_model,
                          temperature=temperature) as attrs:
            start = time.time()
            # Eval tier: use Anthropic SDK directly when key is available
            if self.config.llm_tier == "eval" and self.config.anthropic_api_key:
                try:
                    r = self._call_anthropic(system=system, user=user,
                                             temperature=temperature, max_tokens=max_tokens)
                    r.latency_ms = (time.time() - start) * 1000.0
                    attrs.update({"fallback": False, "cost_usd": r.usd_cost,
                                  "in_tok": r.input_tokens, "out_tok": r.output_tokens,
                                  "provider": "anthropic"})
                    return r
                except Exception as exc:  # noqa: BLE001
                    r = self._fallback(system=system, user=user, error=str(exc))
                    r.latency_ms = (time.time() - start) * 1000.0
                    attrs.update({"fallback": True, "llm_error": str(exc)})
                    return r
            if not self.config.openrouter_api_key:
                r = self._fallback(system=system, user=user)
                r.latency_ms = (time.time() - start) * 1000.0
                attrs.update({"fallback": True, "cost_usd": r.usd_cost,
                              "in_tok": r.input_tokens, "out_tok": r.output_tokens})
                return r
            try:
                import requests  # type: ignore
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.config.openrouter_api_key}"},
                    json={
                        "model": self.config.llm_model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                body = resp.json()
                text = body["choices"][0]["message"]["content"]
                usage = body.get("usage", {})
                in_tok = int(usage.get("prompt_tokens", 0))
                out_tok = int(usage.get("completion_tokens", 0))
                cost = float(body.get("usage", {}).get("cost", 0.0))
                r = LLMResponse(
                    text=text,
                    model=self.config.llm_model,
                    usd_cost=cost,
                    latency_ms=(time.time() - start) * 1000.0,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    fallback_used=False,
                )
                attrs.update({"fallback": False, "cost_usd": cost,
                              "in_tok": in_tok, "out_tok": out_tok})
                return r
            except Exception as exc:  # noqa: BLE001
                r = self._fallback(system=system, user=user, error=str(exc))
                r.latency_ms = (time.time() - start) * 1000.0
                attrs.update({"fallback": True, "llm_error": str(exc)})
                return r

    def _call_anthropic(self, *, system: str, user: str, temperature: float,
                        max_tokens: int) -> LLMResponse:
        import anthropic  # type: ignore
        client = anthropic.Anthropic(api_key=self.config.anthropic_api_key)
        message = client.messages.create(
            model=self.config.llm_model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = message.content[0].text
        in_tok = message.usage.input_tokens
        out_tok = message.usage.output_tokens
        # Approximate cost: claude-sonnet-4-6 pricing ~$3/M in, $15/M out
        cost = (in_tok * 3.0 + out_tok * 15.0) / 1_000_000
        return LLMResponse(
            text=text,
            model=self.config.llm_model,
            usd_cost=cost,
            latency_ms=0.0,  # caller sets this
            input_tokens=in_tok,
            output_tokens=out_tok,
            fallback_used=False,
        )

    def _fallback(self, *, system: str, user: str,
                  error: str | None = None) -> LLMResponse:
        """Deterministic template renderer — interim only.

        It reads the parsed JSON brief that `agent.compose.compose_email`
        passes as `user` and renders the Sequence A.1 template with the
        brief's fields. Not graded — real outputs require a real model.
        """
        try:
            payload = json.loads(user)
        except Exception:
            payload = {}
        text = _render_fallback_email(payload)
        return LLMResponse(
            text=text,
            model="fallback_template",
            usd_cost=0.0,
            latency_ms=0.0,
            input_tokens=len(user) // 4,
            output_tokens=len(text) // 4,
            fallback_used=True,
        )


def _render_fallback_email(payload: dict[str, Any]) -> str:
    brief = payload.get("brief", {})
    contact = payload.get("contact", {})
    company = brief.get("company_name", "your company")
    first = contact.get("first_name", "there")
    seg = (brief.get("segment_assignment") or {}).get("segment")
    jv = (brief.get("signals") or {}).get("job_velocity") or {}
    funding = (brief.get("signals") or {}).get("funding") or {}

    if seg == 1 and funding and jv.get("total", 0) >= 5:
        subject = f"Python hiring velocity after your {funding.get('round', 'round')}"
        body = (
            f"Hi {first},\n\n"
            f"{company} closed a ${funding.get('amount_usd', 0):,} {funding.get('round','')} on "
            f"{funding.get('announced_on','')} — and your public Python roles reached "
            f"{jv.get('python', 0)} out of {jv.get('total', 0)} open engineering roles, "
            f"a change of {jv.get('delta_60d', 0)} over 60 days. The typical bottleneck at this "
            f"stage is recruiting capacity rather than budget.\n\n"
            f"Three companies at similar stage & stack closed this gap with a dedicated squad — "
            f"30 minutes next week to share how it went?\n\n"
            f"— Tenacious"
        )
    elif seg == 2:
        subject = "preserving delivery capacity post-restructure"
        body = (
            f"Hi {first},\n\n"
            f"Tenacious has helped two mid-market teams preserve delivery throughput through "
            f"restructures — net output within 95% CI of pre-RIF baseline by week 9. Not a "
            f"cost-cutting pitch, a capacity-preservation pitch.\n\n"
            f"Worth 30 minutes?\n\n— Tenacious"
        )
    elif seg == 3:
        subject = f"welcome to {company} — quick resource"
        body = (
            f"Hi {first},\n\n"
            f"Congrats on the new role. Most new engineering leaders reassess offshore/vendor "
            f"mix in the first 6 months; happy to send a short note on how peers have approached "
            f"it if useful.\n\n— Tenacious"
        )
    elif seg == 4:
        subject = "quick note on your AI platform work"
        body = (
            f"Hi {first},\n\n"
            f"Saw the public signal on your ML platform direction. We recently shipped a similar "
            f"project for a peer — happy to compare architecture notes over 30 minutes.\n\n"
            f"— Tenacious"
        )
    else:
        subject = "quick note"
        body = (
            f"Hi {first},\n\n"
            f"We research sector-specific engineering-capacity patterns and occasionally share "
            f"short research briefs with leaders at {company}. Let me know if that would be useful.\n\n"
            f"— Tenacious"
        )
    return f"SUBJECT: {subject}\n\n{body}"
