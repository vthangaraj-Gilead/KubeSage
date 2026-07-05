import re
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Tuple


SUPPORTED_INTENTS = [
    "ClusterHealth",
    "NamespaceHealth",
    "PodInvestigation",
    "DeepPodInvestigation",
    "DeepClusterHealth",
    "DeepNamespaceHealth",
    "Help",
    "ResourceListing",
    "UnsupportedAction",
]

UNSUPPORTED_ACTION_KEYWORDS = [
    "delete",
    "remove",
    "destroy",
    "restart",
    "scale",
    "patch",
    "apply",
    "fix",
    "create",
    "cordon",
    "uncordon",
    "drain",
    "edit",
    "update",
    "rollout",
]

HELP_KEYWORDS = [
    "help",
    "what can you do",
    "supported",
    "capabilities",
    "examples",
    "commands",
    "what can kubesage do",
    "how can you help",
]

DEEP_KEYWORDS = [
    "deep",
    "detailed",
    "root cause analysis",
    "root cause",
    "rca",
    "deep analyze",
    "deep analysis",
    "deep investigation",
    "detailed analysis",
    "detailed root cause",
    "perform rca",
    "do rca",
    "run rca",
    "perform root cause analysis",
    "do root cause analysis",
    "run root cause analysis",
]

LISTING_RESOURCE_KEYWORDS = {
    "pods": "Pod",
    "pod": "Pod",
    "workloads": "Workload",
    "workload": "Workload",
}

LISTING_STATUS_KEYWORDS = {
    "not running": "Unhealthy",
    "non running": "Unhealthy",
    "non healthy": "Unhealthy",
    "not healthy": "Unhealthy",
    "no healthy": "Unhealthy",
    "unhealthy": "Unhealthy",
    "problematic pods": "Unhealthy",
    "problematic workloads": "Unhealthy",
    "problematic": "Unhealthy",
    "broken": "Unhealthy",
    "bad": "Unhealthy",
    "stuck": "Unhealthy",
    "failing": "Unhealthy",
    "failed": "Unhealthy",
    "healthy": "Healthy",
    "running": "Running",
    "pending": "Pending",
    "crashloopbackoff": "CrashLoopBackOff",
    "crashlooping": "CrashLoopBackOff",
    "crash looping": "CrashLoopBackOff",
    "imagepullbackoff": "ImagePullBackOff",
    "image pull backoff": "ImagePullBackOff",
    "image pull": "ImagePullBackOff",
}

CAUSE_PATTERNS = [
    r"\boomkilled\b",
    r"\bsecret issue\b",
    r"\bconfig issue\b",
    r"\bconfigmap\b",
    r"\bprobe issue\b",
    r"\bnot ready\b",
    r"\bname resolution\b",
    r"\bdns\b",
    r"\bmount problem\b",
    r"\bpending\b",
    r"\bstorage issue\b",
    r"\bimage pull\b",
    r"\bcommand issue\b",
    r"\bscheduling issue\b",
    r"\bapp crash\b",
    r"\bcrashloop\b",
    r"\bcrash loop\b",
]

TYPO_CORRECTIONS = {
    "pendding": "pending",
    "unhealty": "unhealthy",
    "crashloping": "crashlooping",
    "imagepullbakoff": "imagepullbackoff",
    "runing": "running",
    "worklods": "workloads",
    "analayze": "analyze",
    "analyse": "analyze",
    "investgation": "investigation",
    "failng": "failing",
    "problamatic": "problematic",
    "problemetic": "problematic",
}

GENERIC_NON_NAMESPACE_WORDS = {
    "issue",
    "issues",
    "health",
    "status",
    "problem",
    "problems",
    "broken",
    "failure",
    "failures",
}

RESERVED_NON_WORKLOAD_NAMES = {
    "cluster",
    "namespace",
    "namespaces",
    "health",
    "status",
    "my",
    "on",
}


def _clean_question(question: str) -> str:
    return " ".join((question or "").strip().split())


def _normalized_question(question: str) -> str:
    return _clean_question(question).lower()


def _apply_typo_normalization(question: str) -> str:
    updated = question
    for wrong, right in TYPO_CORRECTIONS.items():
        updated = re.sub(rf"\b{re.escape(wrong)}\b", right, updated, flags=re.IGNORECASE)
    return updated


def _contains_any(text: str, phrases: List[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _find_namespace(question_lower: str) -> str:
    patterns = [
        r"\bnamespace\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\b",
        r"\bin\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bon\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bin\s+(kube-system|kube-public|kube-node-lease|default|ai-investigator-lab|chaos|rstudioworkbench|kubesage)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, question_lower)
        if match:
            candidate = match.group(1)
            if candidate in GENERIC_NON_NAMESPACE_WORDS:
                continue
            return candidate

    return ""


def _extract_explicit_namespace_name(question_lower: str) -> str:
    patterns = [
        r"\bdeep analyze\s+on\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bdeep analyze\s+my\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bdeep analyze\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bdeep analyze\s+namespace\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\b",
        r"\bdeep analysis for\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bdeep investigation for\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bperform rca on\s+my\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bperform rca on\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bdo rca on\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\brun rca on\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bperform root cause analysis on\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bhow is\s+my\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bhow is\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bcheck\s+my\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bcheck\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\s+namespace\b",
        r"\bshow namespace health for\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\b",
        r"\bgive me namespace status for\s+([a-z0-9]([-a-z0-9]*[a-z0-9])?)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, question_lower)
        if match:
            candidate = match.group(1)
            if candidate not in RESERVED_NON_WORKLOAD_NAMES:
                return candidate

    return ""


def _extract_resource_name(question_lower: str) -> str:
    deep_patterns = [
        r"\bdeep analyze\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bdeep analysis for\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bdeep investigation for\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bdetailed analysis for\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bdetailed root cause for\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\broot cause analysis for\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bgive me deep rca for\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bdeep investigation\s+for\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bperform rca on\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bdo rca on\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\brun rca on\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bperform root cause analysis on\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bdo root cause analysis on\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\brun root cause analysis on\s+([a-z0-9][a-z0-9\-]*)\b",
    ]

    for pattern in deep_patterns:
        match = re.search(pattern, question_lower)
        if match:
            candidate = match.group(1)
            if candidate not in RESERVED_NON_WORKLOAD_NAMES:
                return candidate

    explicit_patterns = [
        r"\binvestigate\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\binspect\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bcheck\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\banalyze\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bfor\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bwhy is\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bhow is\s+(?:my\s+)?([a-z0-9][a-z0-9\-]*)\b",
        r"\bwhat happened to\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bwhat is wrong with\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bdoes\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bdid\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bhas\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bis\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bworkload\s+([a-z0-9][a-z0-9\-]*)\b",
        r"\bpod\s+([a-z0-9][a-z0-9\-]*)\b",
    ]

    for pattern in explicit_patterns:
        match = re.search(pattern, question_lower)
        if match:
            candidate = match.group(1)
            if candidate not in {
                "namespace",
                "cluster",
                "pods",
                "pod",
                "workloads",
                "workload",
                "health",
                "status",
                "issue",
                "analysis",
                "investigation",
            } and candidate not in RESERVED_NON_WORKLOAD_NAMES:
                return candidate

    trailing_patterns = [
        r"\b([a-z0-9][a-z0-9\-]*)\s+failing\b",
        r"\b([a-z0-9][a-z0-9\-]*)\s+healthy\b",
        r"\b([a-z0-9][a-z0-9\-]*)\s+pending\b",
        r"\b([a-z0-9][a-z0-9\-]*)\s+down\b",
        r"\b([a-z0-9][a-z0-9\-]*)\s+not working\b",
    ]

    for pattern in trailing_patterns:
        match = re.search(pattern, question_lower)
        if match:
            candidate = match.group(1)
            if candidate not in RESERVED_NON_WORKLOAD_NAMES:
                return candidate

    return ""


def _extract_listing_type(question_lower: str) -> Tuple[str, str]:
    resource_type = ""
    status_filter = "All"

    for key, value in LISTING_RESOURCE_KEYWORDS.items():
        if re.search(rf"\b{re.escape(key)}\b", question_lower):
            resource_type = value
            break

    for key, value in LISTING_STATUS_KEYWORDS.items():
        if key in question_lower:
            status_filter = value
            break

    if resource_type == "Workload" and status_filter in {"Running", "Pending", "CrashLoopBackOff", "ImagePullBackOff"}:
        status_filter = "Unhealthy"

    return resource_type, status_filter


def _is_help(question_lower: str) -> bool:
    return question_lower == "help" or _contains_any(question_lower, HELP_KEYWORDS)


def _is_unsupported_action(question_lower: str) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", question_lower) for word in UNSUPPORTED_ACTION_KEYWORDS)


def _is_deep_request(question_lower: str) -> bool:
    if _contains_any(question_lower, DEEP_KEYWORDS):
        return True

    if "deep" in question_lower and "analyze" in question_lower:
        return True
    if "deep" in question_lower and "analysis" in question_lower:
        return True
    if "deep" in question_lower and "investigation" in question_lower:
        return True
    if "detailed" in question_lower and "root cause" in question_lower:
        return True
    if "perform" in question_lower and "rca" in question_lower:
        return True
    if "do" in question_lower and "rca" in question_lower:
        return True
    if "run" in question_lower and "rca" in question_lower:
        return True
    if "perform" in question_lower and "root cause analysis" in question_lower:
        return True

    return False


def _is_cluster_health(question_lower: str) -> bool:
    cluster_patterns = [
        r"\bcluster health\b",
        r"\bshow cluster\b",
        r"\bcluster status\b",
        r"\boverall cluster status\b",
        r"\bcluster summary\b",
        r"\bhow is my cluster\b",
        r"\bis the cluster healthy\b",
        r"\bcluster issues\b",
        r"\bacross the cluster\b",
        r"\bcluster issue\b",
        r"\banalyze my cluster\b",
        r"\banalyze cluster\b",
        r"\binspect my cluster\b",
        r"\bcheck my cluster\b",
        r"\bcheck cluster\b",
        r"\breview cluster health\b",
        r"\bgive me cluster summary\b",
        r"\btell me cluster health\b",
    ]
    return any(re.search(pattern, question_lower) for pattern in cluster_patterns)


def _is_explicit_cluster_deep_prompt(question_lower: str) -> bool:
    patterns = [
        r"\bdeep analyze my cluster\b",
        r"\bdeep analyze cluster\b",
        r"\bdeep analysis for cluster\b",
        r"\bdeep analysis for my cluster\b",
        r"\bdeep investigation for cluster\b",
        r"\bdeep investigation for my cluster\b",
        r"\bperform rca on cluster\b",
        r"\bperform rca on my cluster\b",
        r"\bdo rca on cluster\b",
        r"\bdo rca on my cluster\b",
        r"\brun rca on cluster\b",
        r"\brun rca on my cluster\b",
        r"\bperform root cause analysis on cluster\b",
        r"\bperform root cause analysis on my cluster\b",
        r"\bdo root cause analysis on cluster\b",
        r"\bdo root cause analysis on my cluster\b",
        r"\brun root cause analysis on cluster\b",
        r"\brun root cause analysis on my cluster\b",
    ]
    return any(re.search(pattern, question_lower) for pattern in patterns)


def _is_namespace_health(question_lower: str, namespace: str) -> bool:
    if not namespace:
        return False

    namespace_patterns = [
        r"\bnamespace health\b",
        r"\bnamespace status\b",
        r"\bhow is namespace\b",
        r"\bis namespace .* healthy\b",
        r"\banalyze namespace\b",
        r"\binspect namespace\b",
        r"\breview namespace\b",
        r"\bwhat is unhealthy in\b",
        r"\bunhealthy pods in\b",
        r"\ball pods healthy\b",
        r"\banything wrong\b",
        r"\bis anything failing\b",
        r"\bwhat is broken\b",
        r"\bhow is [a-z0-9][a-z0-9\-]* namespace\b",
        r"\bcheck [a-z0-9][a-z0-9\-]* namespace\b",
        r"\bcheck my [a-z0-9][a-z0-9\-]* namespace\b",
    ]
    return any(re.search(pattern, question_lower) for pattern in namespace_patterns)


def _is_resource_listing(question_lower: str) -> bool:
    listing_verbs = ["show", "list", "which", "what are", "display"]
    listing_targets = [
        "pods",
        "pod",
        "workloads",
        "workload",
        "healthy",
        "running",
        "pending",
        "unhealthy",
        "problematic",
        "non running",
        "not running",
        "not healthy",
        "non healthy"
        "no healthy",
        "crashlooping",
        "crash looping",
        "image pull backoff",
        "imagepullbackoff",
        "broken",
        "bad",
        "stuck",
        "failing",
        "failed",
    ]

    return any(verb in question_lower for verb in listing_verbs) and any(
        target in question_lower for target in listing_targets
    )


def _is_pod_investigation(question_lower: str) -> bool:
    investigation_patterns = [
        r"\bwhy is\b",
        r"\bhow is\b",
        r"\binvestigate\b",
        r"\binspect\b",
        r"\bcheck\b",
        r"\banalyze\b",
        r"\btroubleshoot\b",
        r"\bdebug\b",
        r"\bwhat happened to\b",
        r"\bwhat is wrong with\b",
        r"\bfailing\b",
        r"\bnot working\b",
        r"\bdown\b",
        r"\bshow workload health\b",
        r"\bshow pod health\b",
        r"\bpod healthy\b",
        r"\bhit image pull issue\b",
        r"\bhaving storage issue\b",
        r"\bfail because of dns\b",
        r"\bfail due to dns\b",
        r"\bhaving dns issue\b",
        r"\bhit secret issue\b",
        r"\bhit config issue\b",
        r"\bhit oomkilled issue\b",
        r"\bhit command issue\b",
        r"\bhit probe issue\b",
        r"\bhit scheduling issue\b",
        r"\bhave image pull issue\b",
        r"\bhaving image pull issue\b",
        r"\bhave storage issue\b",
        r"\bfacing storage issue\b",
        r"\bhaving scheduling issue\b",
    ]

    if any(re.search(pattern, question_lower) for pattern in investigation_patterns):
        return True

    return any(re.search(pattern, question_lower) for pattern in CAUSE_PATTERNS)


def _ambiguous_response(message: str) -> Dict[str, Any]:
    return {
        "intent": "",
        "resource_type": "",
        "resource_name": "",
        "namespace": "",
        "status_filter": "",
        "confidence": 0.4,
        "intent_clarity": "ambiguous",
        "error": message,
    }


def _supported_response(
    intent: str,
    resource_type: str = "",
    resource_name: str = "",
    namespace: str = "",
    status_filter: str = "",
    confidence: float = 0.95,
) -> Dict[str, Any]:
    return {
        "intent": intent,
        "resource_type": resource_type,
        "resource_name": resource_name,
        "namespace": namespace,
        "status_filter": status_filter,
        "confidence": confidence,
        "intent_clarity": "clear",
    }


def _detect_typo_hint(question_lower: str) -> Optional[str]:
    words = re.findall(r"[a-z0-9\-]+", question_lower)
    for word in words:
        if word in TYPO_CORRECTIONS:
            return TYPO_CORRECTIONS[word]

    supported_words = (
        list(TYPO_CORRECTIONS.values())
        + list(LISTING_RESOURCE_KEYWORDS.keys())
        + list(LISTING_STATUS_KEYWORDS.keys())
        + [
            "healthy",
            "running",
            "pending",
            "unhealthy",
            "problematic",
            "workloads",
            "pods",
            "analyze",
            "investigation",
            "failing",
            "cluster",
            "namespace",
        ]
    )

    for word in words:
        if len(word) < 5:
            continue
        match = get_close_matches(word, supported_words, n=1, cutoff=0.84)
        if match and match[0] != word:
            return match[0]

    return None


def _classify_with_rules(question: str) -> Dict[str, Any]:
    cleaned = _clean_question(question)
    normalized = _normalized_question(cleaned)

    typo_hint = _detect_typo_hint(normalized)
    normalized = _normalized_question(_apply_typo_normalization(normalized))

    if normalized == "show unhealthy":
        return _supported_response(
            "ResourceListing",
            resource_type="Pod",
            status_filter="Unhealthy",
            confidence=0.90,
        )

    if not normalized or normalized in {"?", "??", "???", "????"}:
        return _ambiguous_response("Unable to classify intent")

    if _is_help(normalized):
        return _supported_response("Help", resource_type="Help", confidence=0.99)

    if _is_unsupported_action(normalized):
        return _supported_response("UnsupportedAction", confidence=0.99)

    namespace = _find_namespace(normalized)
    resource_name = _extract_resource_name(normalized)
    is_deep = _is_deep_request(normalized)
    explicit_namespace_name = _extract_explicit_namespace_name(normalized)

    if _is_resource_listing(normalized):
        resource_type, status_filter = _extract_listing_type(normalized)
        if not resource_type:
            if typo_hint:
                return _ambiguous_response(f"Intent is unclear. Did you mean '{typo_hint}'?")
            return _ambiguous_response("Unable to classify intent")
        return _supported_response(
            "ResourceListing",
            resource_type=resource_type,
            namespace=namespace,
            status_filter=status_filter,
            confidence=0.97,
        )

    if _is_explicit_cluster_deep_prompt(normalized):
        return _supported_response("DeepClusterHealth", resource_type="Cluster", confidence=0.98)

    if explicit_namespace_name and is_deep:
        return _supported_response(
            "DeepNamespaceHealth",
            resource_type="Namespace",
            resource_name=explicit_namespace_name,
            namespace=explicit_namespace_name,
            confidence=0.98,
        )

    if explicit_namespace_name:
        return _supported_response(
            "NamespaceHealth",
            resource_type="Namespace",
            resource_name=explicit_namespace_name,
            namespace=explicit_namespace_name,
            confidence=0.98,
        )

    if _is_cluster_health(normalized):
        if is_deep:
            return _supported_response("DeepClusterHealth", resource_type="Cluster", confidence=0.97)
        return _supported_response("ClusterHealth", resource_type="Cluster", confidence=0.97)

    if is_deep:
        if namespace and _is_namespace_health(normalized, namespace):
            return _supported_response(
                "DeepNamespaceHealth",
                resource_type="Namespace",
                resource_name=namespace,
                namespace=namespace,
                confidence=0.96,
            )
        if resource_name:
            return _supported_response(
                "DeepPodInvestigation",
                resource_type="Workload",
                resource_name=resource_name,
                namespace=namespace,
                confidence=0.96,
            )
        if typo_hint:
            return _ambiguous_response(f"Intent is unclear. Did you mean '{typo_hint}'?")
        return _ambiguous_response("Unable to classify intent")

    if _is_namespace_health(normalized, namespace):
        return _supported_response(
            "NamespaceHealth",
            resource_type="Namespace",
            resource_name=namespace,
            namespace=namespace,
            confidence=0.97,
        )

    if _is_pod_investigation(normalized):
        if resource_name:
            return _supported_response(
                "PodInvestigation",
                resource_type="Workload",
                resource_name=resource_name,
                namespace=namespace,
                confidence=0.95,
            )
        if typo_hint:
            return _ambiguous_response(f"Intent is unclear. Did you mean '{typo_hint}'?")
        return _ambiguous_response("Intent is unclear")

    if normalized in {"cluster issue maybe", "overall cluster status"}:
        return _supported_response("ClusterHealth", resource_type="Cluster", confidence=0.90)

    if typo_hint:
        return _ambiguous_response(f"Intent is unclear. Did you mean '{typo_hint}'?")

    return _ambiguous_response("Unable to classify intent")


def classify_intent(question: str) -> Dict[str, Any]:
    return _classify_with_rules(question)