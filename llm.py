import json
from typing import Any, Dict, List

import requests
import os


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = "llama3.1"


def _truncate_text(value: Any, max_length: int = 4000) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[:max_length] + "\n...[truncated]"


def _normalize_recommendations(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _normalize_evidence_points(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty response from Ollama")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        return json.loads(candidate)

    raise ValueError("No valid JSON object found in Ollama response")


def _call_ollama(prompt: str) -> str:
    request_payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "stream": False,
    }

    response = requests.post(OLLAMA_URL, json=request_payload, timeout=1800)
    response.raise_for_status()

    result = response.json()
    return result.get("message", {}).get("content", "")


def _repair_json_response(raw_text: str) -> Dict[str, Any]:
    repair_prompt = f"""
Convert the following Kubernetes RCA output into valid JSON only.

Return exactly one JSON object with this schema:
{{
  "root_cause": "string",
  "category": "ImagePullFailure|SecretConfigFailure|ConfigMapFailure|StoragePVCFailure|SchedulingNodeSelectorFailure|SchedulingFailure|LivenessProbeFailure|ReadinessProbeFailure|DNSResolutionFailure|OOMKilled|CrashLoopApplicationFailure|BadCommandOrEntrypoint|Unknown",
  "evidence": "string",
  "evidence_points": ["string", "string"],
  "confidence": "High|Medium|Low",
  "recommendations": ["string", "string"]
}}

Rules:
- Output JSON only.
- Do not include markdown.
- Do not include explanation.
- Keep the response focused only on the target pod/workload.
- Ignore unrelated pods, deployments, or namespace-wide failures unless explicitly tied to the target pod/workload.
- If a field is missing, infer the safest reasonable value from the text.
- If category is unclear, use "Unknown".

Text to convert:
{raw_text}
""".strip()

    repaired_text = _call_ollama(repair_prompt)
    return _extract_json(repaired_text)


def analyze_investigation(investigation_data: Dict[str, Any]) -> str:
    payload_data = {
        "pod_name": investigation_data.get("pod_name", ""),
        "namespace": investigation_data.get("namespace", ""),
        "describe": _truncate_text(investigation_data.get("describe", ""), 4000),
        "logs": _truncate_text(investigation_data.get("logs", ""), 2500),
        "previous_logs": _truncate_text(investigation_data.get("previous_logs", ""), 3000),
        "events": _truncate_text(investigation_data.get("events", ""), 2500),
        "pvc": _truncate_text(investigation_data.get("pvc", ""), 1500),
        "node_info": _truncate_text(investigation_data.get("node_info", ""), 1500),
        "deployment_info": _truncate_text(investigation_data.get("deployment_info", ""), 1500),
    }

    prompt = f"""
You are a Kubernetes root cause analysis assistant.

You will be given structured investigation evidence for one target pod/workload.

Target pod:
- pod_name: {payload_data["pod_name"]}
- namespace: {payload_data["namespace"]}

Your task:
1. Identify the most likely root cause for the target pod/workload only.
2. Classify the failure into one category.
3. Summarize the strongest supporting evidence for the target pod/workload only.
4. Extract 1 to 3 concrete evidence points about the target pod/workload only.
5. Assign confidence as exactly one of: High, Medium, Low.
6. Provide short actionable recommendations for the target pod/workload only.

Preferred categories when supported by evidence:
- ImagePullFailure
- SecretConfigFailure
- ConfigMapFailure
- StoragePVCFailure
- SchedulingNodeSelectorFailure
- SchedulingFailure
- LivenessProbeFailure
- ReadinessProbeFailure
- DNSResolutionFailure
- OOMKilled
- CrashLoopApplicationFailure
- BadCommandOrEntrypoint
- Unknown

Strict scope rules:
- Focus only on the target pod/workload.
- Ignore unrelated pods, deployments, or namespace-wide failures.
- Do not summarize cluster-wide or namespace-wide issues unless they directly explain the target pod/workload.
- If namespace PVC output contains multiple PVCs, only use it if it clearly relates to the target pod/workload.
- If there is not enough target-specific evidence, say so and keep the category conservative.

Strict output rules:
- Return JSON only.
- Do not include markdown.
- Do not include explanations outside JSON.
- confidence must be exactly one of: "High", "Medium", "Low"
- recommendations must be a JSON array of strings
- evidence must be a short string summary, not a list
- evidence_points must be a JSON array of 1 to 3 short strings when possible
- category must be one of the listed categories
- Do not invent facts not present in the provided data.
- Recommendations must directly address the observed evidence.
- If the evidence already clearly shows the cause, do NOT suggest generic steps like "check logs" or "investigate further".
- Only suggest "check logs" if logs are missing or inconclusive.
- Only suggest image-related actions if the evidence indicates an image pull problem.
- Only suggest PVC/storage actions if the evidence indicates a storage-related issue.
- Only suggest probe actions if the evidence indicates liveness/readiness probe failure.
- Prefer concrete fixes over broad troubleshooting advice.
- When possible, distinguish liveness probe failures from readiness probe failures.
- When possible, mention exact Kubernetes reason names such as ImagePullBackOff, ErrImagePull, CreateContainerConfigError, OOMKilled, FailedScheduling, Liveness probe failed, or Readiness probe failed.

Required JSON format:
{{
  "root_cause": "string",
  "category": "ImagePullFailure|SecretConfigFailure|ConfigMapFailure|StoragePVCFailure|SchedulingNodeSelectorFailure|SchedulingFailure|LivenessProbeFailure|ReadinessProbeFailure|DNSResolutionFailure|OOMKilled|CrashLoopApplicationFailure|BadCommandOrEntrypoint|Unknown",
  "evidence": "string",
  "evidence_points": ["string", "string"],
  "confidence": "High|Medium|Low",
  "recommendations": ["string", "string"]
}}

Investigation data:
{json.dumps(payload_data, indent=2)}
""".strip()

    content = _call_ollama(prompt)

    try:
        parsed = _extract_json(content)
    except Exception:
        try:
            parsed = _repair_json_response(content)
        except Exception:
            parsed = {
                "root_cause": "Unable to produce a fully structured AI root cause summary from the model output.",
                "category": "Unknown",
                "evidence": "",
                "evidence_points": [],
                "confidence": "Medium",
                "recommendations": [],
            }

    root_cause = str(parsed.get("root_cause", "")).strip()
    category = str(parsed.get("category", "Unknown")).strip()
    evidence = str(parsed.get("evidence", "")).strip()
    evidence_points = _normalize_evidence_points(parsed.get("evidence_points", []))
    confidence = str(parsed.get("confidence", "Medium")).strip()
    recommendations = _normalize_recommendations(parsed.get("recommendations", []))

    allowed_categories = {
        "ImagePullFailure",
        "SecretConfigFailure",
        "ConfigMapFailure",
        "StoragePVCFailure",
        "SchedulingNodeSelectorFailure",
        "SchedulingFailure",
        "LivenessProbeFailure",
        "ReadinessProbeFailure",
        "DNSResolutionFailure",
        "OOMKilled",
        "CrashLoopApplicationFailure",
        "BadCommandOrEntrypoint",
        "Unknown",
    }

    if confidence not in {"High", "Medium", "Low"}:
        confidence = "Medium"

    if category not in allowed_categories:
        category = "Unknown"

    normalized = {
        "root_cause": root_cause,
        "category": category,
        "evidence": evidence,
        "evidence_points": evidence_points,
        "confidence": confidence,
        "recommendations": recommendations,
    }

    return json.dumps(normalized)
