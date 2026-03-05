import json
import logging
from datetime import datetime, timezone
from urllib import request as url_request

from config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_API_VERSION,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    RISK_HIGH,
    RISK_CRITICAL,
)

log = logging.getLogger(__name__)

FRAUD_SYSTEM_PROMPT = """You are a fraud detection analyst for the ARES authentication system.
Analyze the login attempt context provided and return your assessment as a JSON object with exactly these keys:

- "verdict": one of "HIGH_RISK", "MEDIUM_RISK", or "LOW_RISK"
- "reasoning": a 2-3 sentence explanation of your analysis
- "recommendation": one of "lock_account", "challenge_user", or "allow_with_monitoring"

Rules:
- If there are 10+ consecutive failed attempts or signs of brute-force, verdict must be HIGH_RISK with recommendation lock_account.
- If there is high login velocity (many attempts in short time), verdict should be at least MEDIUM_RISK with recommendation challenge_user.
- A new IP alone with no other factors is LOW_RISK with recommendation allow_with_monitoring.
- Combine multiple factors: new IP + failed attempts + velocity = higher risk.

Return ONLY the JSON object, no markdown fences, no extra text."""


class FraudAnalysisService:
    def __init__(self):
        self._provider = None
        self._gemini_client = None
        self._init_provider()

    def _init_provider(self):
        if AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT:
            self._provider = "azure_openai"
            log.info(
                "Azure OpenAI configured – LLM fraud analysis enabled (deployment: %s)",
                AZURE_OPENAI_DEPLOYMENT,
            )
        elif GEMINI_API_KEY:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=GEMINI_API_KEY)
                self._provider = "gemini"
                log.info(
                    "Gemini API configured – LLM fraud analysis enabled (model: %s)",
                    GEMINI_MODEL,
                )
            except ImportError:
                log.warning(
                    "google-genai package not installed – falling back to simulated fraud analysis"
                )
        else:
            log.warning("No LLM API keys set – falling back to simulated fraud analysis")

    def analyze(self, email, ip_address, user_agent, risk_score, risk_factors):
        prompt_context = {
            "email": email,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "risk_score": risk_score,
            "risk_factors": risk_factors,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if self._provider == "azure_openai":
            try:
                raw_text = self._call_azure_openai(prompt_context)
                if raw_text.startswith("```"):
                    raw_text = raw_text.split("\n", 1)[1]
                    raw_text = raw_text.rsplit("```", 1)[0].strip()
                result = json.loads(raw_text)
                for key in ("verdict", "reasoning", "recommendation"):
                    if key not in result:
                        raise ValueError(f"Missing key '{key}' in Azure OpenAI response")
                result["prompt_context"] = prompt_context
                result["model"] = AZURE_OPENAI_DEPLOYMENT
                result["analyzed_at"] = datetime.now(timezone.utc).isoformat()
                log.info(
                    "Azure OpenAI fraud analysis: verdict=%s recommendation=%s",
                    result["verdict"],
                    result["recommendation"],
                )
                return result
            except Exception as e:
                log.error("Azure OpenAI API call failed, falling back to simulation: %s", e)

        elif self._provider == "gemini" and self._gemini_client:
            try:
                from google.genai import types as genai_types
                response = self._gemini_client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=f"Analyze this login attempt:\n{json.dumps(prompt_context, indent=2)}",
                    config=genai_types.GenerateContentConfig(
                        system_instruction=FRAUD_SYSTEM_PROMPT,
                        temperature=0.2,
                    ),
                )
                raw_text = response.text.strip()
                if raw_text.startswith("```"):
                    raw_text = raw_text.split("\n", 1)[1]
                    raw_text = raw_text.rsplit("```", 1)[0].strip()
                result = json.loads(raw_text)
                for key in ("verdict", "reasoning", "recommendation"):
                    if key not in result:
                        raise ValueError(f"Missing key '{key}' in Gemini response")
                result["prompt_context"] = prompt_context
                result["model"] = GEMINI_MODEL
                result["analyzed_at"] = datetime.now(timezone.utc).isoformat()
                log.info(
                    "Gemini fraud analysis: verdict=%s recommendation=%s",
                    result["verdict"],
                    result["recommendation"],
                )
                return result
            except Exception as e:
                log.error("Gemini API call failed, falling back to simulation: %s", e)

        return self._simulate(prompt_context)

    def _call_azure_openai(self, prompt_context):
        url = (
            f"{AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/"
            f"{AZURE_OPENAI_DEPLOYMENT}/chat/completions"
            f"?api-version={AZURE_OPENAI_API_VERSION}"
        )
        body = {
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": FRAUD_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Analyze this login attempt:\n{json.dumps(prompt_context, indent=2)}",
                },
            ],
        }
        encoded = json.dumps(body).encode("utf-8")
        req = url_request.Request(
            url,
            data=encoded,
            headers={
                "api-key": AZURE_OPENAI_API_KEY,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with url_request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def _simulate(self, prompt_context):
        recommendation = "allow_with_monitoring"
        verdict = "LOW_RISK"

        if prompt_context["risk_score"] >= RISK_CRITICAL:
            verdict = "HIGH_RISK"
            recommendation = "lock_account"
        elif prompt_context["risk_score"] >= RISK_HIGH:
            verdict = "MEDIUM_RISK"
            recommendation = "challenge_user"

        reasoning = (
            f"Rule-based fallback evaluated risk score {prompt_context['risk_score']}/100 "
            f"with factors: {', '.join(prompt_context['risk_factors']) or 'none'}."
        )

        return {
            "verdict": verdict,
            "reasoning": reasoning,
            "recommendation": recommendation,
            "prompt_context": prompt_context,
            "model": "rule-based-fallback",
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }
