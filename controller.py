import json
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Set, Tuple

from collectors import get_cluster_pods, get_nodes, get_pods
from health import check_cluster_health, check_namespace_health, check_pod_health
from help_text import get_help_text
from intent_classification import classify_intent

try:
    from investigator import investigate_pod  # type: ignore
except Exception:
    investigate_pod = None

try:
    from llm import analyze_investigation  # type: ignore
except Exception:
    analyze_investigation = None


def _normalize_confidence(value: Any) -> str:
    if isinstance(value, (int, float)):
        if value >= 0.90:
            return "High"
        if value >= 0.70:
            return "Medium"
        return "Low"

    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"high", "medium", "low"}:
            return lowered.capitalize()

    return "Medium"


def _build_base_response(
    question: str,
    intent_result: Optional[Dict[str, Any]] = None,
    resource: str = "",
    resource_type: str = "",
) -> Dict[str, Any]:
    intent_result = intent_result or {}

    return {
        "question": question,
        "intent": intent_result.get("intent", ""),
        "resource": resource or intent_result.get("resource_name", ""),
        "resource_type": resource_type or intent_result.get("resource_type", ""),
        "status": "",
        "health_score": 0,
        "summary": "",
        "root_cause": "",
        "evidence": "",
        "confidence": _normalize_confidence(intent_result.get("confidence", 0.0)),
        "recommendations": [],
    }


def _build_error_response(
    question: str,
    message: str,
    intent_result: Optional[Dict[str, Any]] = None,
    resource: str = "",
    resource_type: str = "",
    confidence: str = "Low",
) -> Dict[str, Any]:
    response = _build_base_response(
        question=question,
        intent_result=intent_result,
        resource=resource,
        resource_type=resource_type,
    )
    response["status"] = "Error"
    response["summary"] = message
    response["confidence"] = confidence
    return response


def _build_ambiguous_intent_response(question: str, intent_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    message = intent_result.get("error") if intent_result else ""
    if not message:
        message = (
            "Intent is unclear. Please provide a more specific prompt for efficient results. "
            "Examples: 'How is my cluster?', 'How is namespace kube-system?', "
            "'Why is crashloop-demo failing?', 'show running pods in kube-system', "
            "'show unhealthy workloads in chaos', or type 'help' to see capabilities."
        )
    return _build_error_response(
        question=question,
        message=message,
        intent_result=intent_result,
        confidence="Low",
    )


def _process_help(question: str, intent_result: Dict[str, Any]) -> Dict[str, Any]:
    response = _build_base_response(
        question=question,
        intent_result=intent_result,
        resource_type="Help",
    )
    response.update(
        {
            "status": "Success",
            "summary": get_help_text(),
            "confidence": "High",
        }
    )
    return response


def _process_unsupported_action(question: str, intent_result: Dict[str, Any]) -> Dict[str, Any]:
    response = _build_base_response(
        question=question,
        intent_result=intent_result,
    )
    response.update(
        {
            "status": "Error",
            "summary": (
                "This investigator currently supports read-only troubleshooting and status queries. "
                "It does not perform changes such as create, delete, patch, scale, restart, cordon, "
                "uncordon, drain, or automatic fixes."
            ),
            "confidence": "High",
            "recommendations": [
                "Ask for cluster, namespace, workload, or pod health.",
                "Use listing prompts such as 'show unhealthy workloads in ai-investigator-lab'.",
                "Use investigation prompts such as 'Why is bad-image failing?'.",
            ],
        }
    )
    return response


def _match_workload_pods(
    pods: List[Dict[str, Any]],
    resource_name: str,
    namespace_hint: str = "",
) -> List[Dict[str, Any]]:
    resource_name = (resource_name or "").strip().lower()
    namespace_hint = (namespace_hint or "").strip().lower()

    if not resource_name:
        return []

    exact_label_matches: List[Dict[str, Any]] = []
    exact_pod_matches: List[Dict[str, Any]] = []
    prefix_matches: List[Dict[str, Any]] = []

    for pod in pods:
        metadata = pod.get("metadata", {}) or {}
        pod_name = (metadata.get("name") or "").lower()
        pod_namespace = (metadata.get("namespace") or "").lower()
        labels = metadata.get("labels", {}) or {}

        app_label = str(labels.get("app", "")).lower()
        app_name_label = str(labels.get("app.kubernetes.io/name", "")).lower()

        if namespace_hint and pod_namespace != namespace_hint:
            continue

        if app_label == resource_name or app_name_label == resource_name:
            exact_label_matches.append(pod)
            continue

        if pod_name == resource_name:
            exact_pod_matches.append(pod)
            continue

        if pod_name.startswith(f"{resource_name}-"):
            prefix_matches.append(pod)

    if exact_label_matches:
        return exact_label_matches
    if exact_pod_matches:
        return exact_pod_matches
    return prefix_matches


def _summarize_pod_health_results(results: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    healthy = [result for result in results if result.get("healthy", False)]
    unhealthy = [result for result in results if not result.get("healthy", False)]
    return healthy, unhealthy


def _build_pod_issue_evidence(unhealthy_results: List[Dict[str, Any]]) -> str:
    lines: List[str] = []

    for result in unhealthy_results:
        namespace = result.get("namespace", "default")
        pod_name = result.get("pod_name", "unknown")
        issues = result.get("issues", []) or []

        if issues:
            for issue in issues:
                lines.append(f"{namespace}/{pod_name}: {issue}")
        else:
            lines.append(f"{namespace}/{pod_name}: unhealthy")

    return "\n".join(lines)


def _append_ai_evidence(
    raw_evidence: str,
    category: str = "",
    evidence_summary: str = "",
    evidence_points: Optional[List[str]] = None,
) -> str:
    evidence_points = evidence_points or []
    parts = [raw_evidence.strip()] if raw_evidence.strip() else []

    if category and category != "Unknown":
        parts.append(f"AI category: {category}")

    if evidence_summary:
        parts.append(f"AI evidence summary: {evidence_summary}")

    if evidence_points:
        formatted_points = "\n".join(f"- {point}" for point in evidence_points if point.strip())
        if formatted_points:
            parts.append(f"AI evidence points:\n{formatted_points}")

    return "\n".join(parts).strip()


def _get_all_namespaces_from_cluster() -> List[str]:
    cluster_pods_result = get_cluster_pods()
    if not cluster_pods_result.get("success", False):
        return []

    cluster_pods = ((cluster_pods_result.get("data") or {}).get("items")) or []
    namespaces = {
        ((pod.get("metadata", {}) or {}).get("namespace", "")).strip()
        for pod in cluster_pods
        if ((pod.get("metadata", {}) or {}).get("namespace", "")).strip()
    }
    return sorted(namespaces)


def _get_all_workload_candidates_from_cluster(namespace_hint: str = "") -> List[str]:
    cluster_pods_result = get_cluster_pods()
    if not cluster_pods_result.get("success", False):
        return []

    cluster_pods = ((cluster_pods_result.get("data") or {}).get("items")) or []
    logical_candidates: Set[str] = set()
    pod_candidates: Set[str] = set()
    namespace_hint = (namespace_hint or "").strip().lower()

    for pod in cluster_pods:
        metadata = pod.get("metadata", {}) or {}
        labels = metadata.get("labels", {}) or {}
        pod_namespace = (metadata.get("namespace") or "").lower()

        if namespace_hint and pod_namespace != namespace_hint:
            continue

        pod_name = (metadata.get("name") or "").strip()
        app_label = str(labels.get("app", "")).strip()
        app_name_label = str(labels.get("app.kubernetes.io/name", "")).strip()

        if app_name_label:
            logical_candidates.add(app_name_label)

        if app_label:
            logical_candidates.add(app_label)

        if pod_name:
            pod_candidates.add(pod_name)

            parts = pod_name.split("-")
            if len(parts) >= 3:
                possible_workload = "-".join(parts[:-2])
                if possible_workload:
                    logical_candidates.add(possible_workload)

    return sorted(logical_candidates) + sorted(pod_candidates - logical_candidates)


def _closest_matches(name: str, candidates: List[str], limit: int = 3, cutoff: float = 0.6) -> List[str]:
    if not name or not candidates:
        return []

    return get_close_matches(name, candidates, n=limit, cutoff=cutoff)


def _infer_workload_name(pod: Dict[str, Any]) -> str:
    metadata = pod.get("metadata", {}) or {}
    labels = metadata.get("labels", {}) or {}
    pod_name = (metadata.get("name") or "").strip()

    app_name_label = str(labels.get("app.kubernetes.io/name", "")).strip()
    if app_name_label:
        return app_name_label

    app_label = str(labels.get("app", "")).strip()
    if app_label:
        return app_label

    parts = pod_name.split("-")
    if len(parts) >= 3:
        return "-".join(parts[:-2])

    return pod_name


def _build_listing_response(
    question: str,
    intent_result: Dict[str, Any],
    summary: str,
    list_title: str,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    response = _build_base_response(
        question=question,
        intent_result=intent_result,
        resource=intent_result.get("namespace", "") or intent_result.get("resource_name", ""),
        resource_type=intent_result.get("resource_type", ""),
    )
    response.update(
        {
            "status": "Success",
            "summary": summary,
            "list_title": list_title,
            "items": items,
            "confidence": "High",
        }
    )
    return response


def _build_deep_rca_root_cause(unhealthy_results: List[Dict[str, Any]]) -> str:
    issues_text = " ".join(
        issue.lower()
        for result in unhealthy_results
        for issue in (result.get("issues", []) or [])
    )

    if "oomkilled" in issues_text:
        return "The workload is likely being terminated because it exceeds its memory limit or available memory."
    if "imagepullbackoff" in issues_text or "errimagepull" in issues_text:
        return "The workload cannot start because the container image cannot be pulled successfully."
    if "createcontainerconfigerror" in issues_text:
        return "The workload is blocked by missing or invalid configuration such as a Secret, ConfigMap, or referenced key."
    if "notready" in issues_text or "not ready" in issues_text:
        return "The workload is running but failing readiness checks, so Kubernetes is not marking it ready."
    if "crashloopbackoff" in issues_text:
        return "The workload is repeatedly crashing and Kubernetes is backing off restarts."
    if "pending" in issues_text:
        return "The workload is not scheduling or initializing successfully and remains pending."
    return "The workload is unhealthy based on current pod state and container status."


def _basic_investigation_recommendations(
    unhealthy_results: List[Dict[str, Any]],
    resource_name: str = "",
) -> List[str]:
    issues_text = " ".join(
        issue.lower()
        for result in unhealthy_results
        for issue in (result.get("issues", []) or [])
    )
    resource_name = (resource_name or "").lower()

    if "oomkilled" in issues_text:
        return [
            "Review memory limits and requests.",
            "Check whether the process is allocating more memory than allowed.",
            "Inspect recent restart count and last terminated state.",
        ]

    if "imagepullbackoff" in issues_text or "errimagepull" in issues_text:
        return [
            "Verify the container image name and tag.",
            "Check whether the image exists and can be pulled from the registry.",
            "Confirm image pull credentials if the registry is private.",
        ]

    if "createcontainerconfigerror" in issues_text and "secret" in resource_name:
        return [
            "Verify the Secret exists in the namespace.",
            "Check Secret name and required key names.",
            "Review envFrom, env.valueFrom, and volume secret references.",
        ]

    if "createcontainerconfigerror" in issues_text and "configmap" in resource_name:
        return [
            "Verify the ConfigMap exists in the namespace.",
            "Check referenced ConfigMap key names.",
            "Review environment variable and volume references to the ConfigMap.",
        ]

    if "createcontainerconfigerror" in issues_text:
        return [
            "Check referenced ConfigMaps, Secrets, and required keys.",
            "Verify environment variable and volume references.",
            "Confirm all required configuration resources exist in the namespace.",
        ]

    if "secret-volume" in resource_name or ("volume" in resource_name and "secret" in resource_name):
        return [
            "Verify the referenced Secret exists in the namespace.",
            "Check secret volume name, mount path, and item key mappings.",
            "Review pod events for mount or volume setup failures.",
        ]

    if "pvc" in resource_name or "persistentvolumeclaim" in issues_text:
        return [
            "Verify the PVC exists and is bound.",
            "Check StorageClass, PV binding, and volume attach events.",
            "Review scheduling and mount events for the pod.",
        ]

    if "node-selector" in resource_name:
        return [
            "Verify nodeSelector keys and values on the workload.",
            "Check whether any nodes actually have the required labels.",
            "Review scheduling events and taints/tolerations if applicable.",
        ]

    if "dns" in resource_name or "name resolution" in issues_text:
        return [
            "Check DNS resolution from inside the pod.",
            "Verify CoreDNS is healthy and reachable.",
            "Review service names, namespaces, and any network policy constraints.",
        ]

    if "probe" in resource_name and ("not ready" in issues_text or "crashloopbackoff" in issues_text):
        return [
            "Check probe configuration such as path, port, and scheme.",
            "Review initialDelaySeconds, timeoutSeconds, and failureThreshold.",
            "Verify the application is listening and responding as expected.",
        ]

    if "not ready" in issues_text or "readiness" in issues_text:
        return [
            "Check readiness probe configuration and target endpoint.",
            "Verify the application is listening on the expected port and path.",
            "Inspect pod events and recent restarts.",
        ]

    if "crashloopbackoff" in issues_text:
        return [
            "Check container startup command, arguments, and application behavior.",
            "Review container logs for the failing pod.",
            "Inspect restart count and last terminated state.",
        ]

    if "pending" in issues_text:
        return [
            "Check scheduling constraints, PVC availability, and node selection rules.",
            "Review pod events for scheduling or mount failures.",
            "Verify referenced storage resources exist and can bind.",
        ]

    return [
        "Inspect pod events and container status details.",
        "Review container logs for the affected pod.",
        "Validate referenced configuration, storage, and probe settings.",
    ]


def _maybe_run_deep_rca(
    question: str,
    resource_name: str,
    namespace_hint: str,
    matched_pods: List[Dict[str, Any]],
    unhealthy_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    fallback = {
        "root_cause": _build_deep_rca_root_cause(unhealthy_results),
        "recommendations": _basic_investigation_recommendations(unhealthy_results, resource_name=resource_name),
        "evidence": "",
        "evidence_points": [],
        "category": "Unknown",
        "confidence": "High",
    }

    if investigate_pod is None or analyze_investigation is None or not matched_pods:
        return fallback

    try:
        primary_pod = matched_pods[0]
        metadata = primary_pod.get("metadata", {}) or {}
        pod_name = metadata.get("name", "")
        namespace = metadata.get("namespace", namespace_hint or "default")

        if not pod_name:
            return fallback

        investigation_raw = investigate_pod(namespace=namespace, pod_name=pod_name)

        investigation_payload = {
            "pod_name": pod_name,
            "namespace": namespace,
            "describe": investigation_raw.get("describe", ""),
            "logs": investigation_raw.get("logs", ""),
            "previous_logs": investigation_raw.get("previous_logs", ""),
            "events": investigation_raw.get("events", ""),
            "pvc": investigation_raw.get("pvc", ""),
            "node_info": investigation_raw.get("node_info", ""),
            "deployment_info": investigation_raw.get("deployment_info", ""),
        }

        analysis_raw = analyze_investigation(investigation_payload)

        parsed = json.loads(analysis_raw) if isinstance(analysis_raw, str) else analysis_raw
        if not isinstance(parsed, dict):
            return fallback

        root_cause = str(parsed.get("root_cause", "")).strip() or fallback["root_cause"]
        evidence = str(parsed.get("evidence", "")).strip()
        category = str(parsed.get("category", "Unknown")).strip()
        confidence = str(parsed.get("confidence", "High")).strip()
        recommendations = parsed.get("recommendations", [])
        evidence_points = parsed.get("evidence_points", [])

        if not isinstance(recommendations, list):
            recommendations = []
        recommendations = [str(item).strip() for item in recommendations if str(item).strip()]

        if not isinstance(evidence_points, list):
            evidence_points = []
        evidence_points = [str(item).strip() for item in evidence_points if str(item).strip()]

        if confidence not in {"High", "Medium", "Low"}:
            confidence = "High"

        if not category:
            category = "Unknown"

        if not recommendations:
            recommendations = fallback["recommendations"]

        return {
            "root_cause": root_cause,
            "recommendations": recommendations,
            "evidence": evidence,
            "evidence_points": evidence_points,
            "category": category,
            "confidence": confidence,
        }
    except Exception:
        return fallback


def _process_resource_listing(question: str, intent_result: Dict[str, Any]) -> Dict[str, Any]:
    resource_type = intent_result.get("resource_type", "")
    namespace = intent_result.get("namespace", "")
    status_filter = intent_result.get("status_filter", "All")

    if resource_type == "Pod":
        if namespace:
            pods_result = get_pods(namespace)
            if not pods_result.get("success", False):
                suggestions = _closest_matches(namespace, _get_all_namespaces_from_cluster(), limit=2, cutoff=0.65)
                suggestion_text = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
                return _build_error_response(
                    question=question,
                    message=pods_result.get(
                        "error",
                        f"Namespace '{namespace}' does not exist or pods could not be fetched."
                    ) + suggestion_text,
                    intent_result=intent_result,
                    resource=namespace,
                    resource_type="Namespace",
                    confidence="High" if suggestions else "Medium",
                )
            pods = ((pods_result.get("data") or {}).get("items")) or []
        else:
            pods_result = get_cluster_pods()
            if not pods_result.get("success", False):
                return _build_error_response(
                    question=question,
                    message=pods_result.get("error", "Failed to get cluster pod information."),
                    intent_result=intent_result,
                    resource="cluster",
                    resource_type="Cluster",
                    confidence="Low",
                )
            pods = ((pods_result.get("data") or {}).get("items")) or []

        items: List[Dict[str, Any]] = []

        for pod in pods:
            metadata = pod.get("metadata", {}) or {}
            pod_name = metadata.get("name", "unknown")
            pod_namespace = metadata.get("namespace", "default")
            phase = ((pod.get("status", {}) or {}).get("phase", "Unknown"))
            pod_health = check_pod_health(pod)
            issues = pod_health.get("issues", []) or []

            include = False
            status_text = phase

            if status_filter == "All":
                include = True
            elif status_filter == "Running":
                include = phase == "Running" and pod_health.get("healthy", False)
                status_text = "Running"
            elif status_filter == "Pending":
                include = phase == "Pending"
            elif status_filter == "Unhealthy":
                include = not pod_health.get("healthy", False)
                if issues:
                    status_text = issues[0]
            elif status_filter == "CrashLoopBackOff":
                include = any("crashloopbackoff" in issue.lower() for issue in issues)
                status_text = "CrashLoopBackOff"
            elif status_filter == "ImagePullBackOff":
                include = any(
                    "imagepullbackoff" in issue.lower() or "errimagepull" in issue.lower()
                    for issue in issues
                )
                status_text = "ImagePullBackOff"

            if include:
                if status_filter in {"All", "Pending"} and issues:
                    status_text = issues[0]

                items.append(
                    {
                        "resource_type": "Pod",
                        "namespace": pod_namespace,
                        "name": pod_name,
                        "status": status_text,
                    }
                )

        items = sorted(items, key=lambda item: (item.get("namespace", ""), item.get("name", "")))

        location = f"namespace '{namespace}'" if namespace else "the cluster"
        filter_label = status_filter.lower() if status_filter != "All" else "all"

        return _build_listing_response(
            question=question,
            intent_result=intent_result,
            summary=f"Found {len(items)} {filter_label} pods in {location}.",
            list_title=f"{status_filter if status_filter != 'All' else 'All'} pods in {location}:",
            items=items,
        )

    if resource_type == "Workload":
        if namespace:
            namespace_check = get_pods(namespace)
            if not namespace_check.get("success", False):
                suggestions = _closest_matches(namespace, _get_all_namespaces_from_cluster(), limit=2, cutoff=0.65)
                suggestion_text = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
                return _build_error_response(
                    question=question,
                    message=namespace_check.get(
                        "error",
                        f"Namespace '{namespace}' does not exist or workloads could not be fetched."
                    ) + suggestion_text,
                    intent_result=intent_result,
                    resource=namespace,
                    resource_type="Namespace",
                    confidence="High" if suggestions else "Medium",
                )

        pods_result = get_cluster_pods()
        if not pods_result.get("success", False):
            return _build_error_response(
                question=question,
                message=pods_result.get("error", "Failed to get cluster pod information."),
                intent_result=intent_result,
                resource="cluster",
                resource_type="Cluster",
                confidence="Low",
            )

        pods = ((pods_result.get("data") or {}).get("items")) or []
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

        for pod in pods:
            metadata = pod.get("metadata", {}) or {}
            pod_namespace = metadata.get("namespace", "default")

            if namespace and pod_namespace != namespace:
                continue

            workload_name = _infer_workload_name(pod)
            key = (pod_namespace, workload_name)
            grouped.setdefault(key, []).append(pod)

        items: List[Dict[str, Any]] = []

        for (pod_namespace, workload_name), workload_pods in grouped.items():
            pod_results = [check_pod_health(pod) for pod in workload_pods]
            healthy_count = sum(1 for result in pod_results if result.get("healthy", False))
            unhealthy_results = [result for result in pod_results if not result.get("healthy", False)]

            include = False
            status_text = f"{healthy_count}/{len(workload_pods)} healthy"

            if status_filter == "Unhealthy":
                include = len(unhealthy_results) > 0
                if unhealthy_results and unhealthy_results[0].get("issues"):
                    status_text = unhealthy_results[0]["issues"][0]
                elif unhealthy_results:
                    status_text = "Unhealthy"
            elif status_filter == "All":
                include = True

            if include:
                items.append(
                    {
                        "resource_type": "Workload",
                        "namespace": pod_namespace,
                        "name": workload_name,
                        "status": status_text,
                    }
                )

        items = sorted(items, key=lambda item: (item.get("namespace", ""), item.get("name", "")))

        location = f"namespace '{namespace}'" if namespace else "the cluster"
        filter_label = status_filter.lower() if status_filter != "All" else "all"

        return _build_listing_response(
            question=question,
            intent_result=intent_result,
            summary=f"Found {len(items)} {filter_label} workloads in {location}.",
            list_title=f"{status_filter if status_filter != 'All' else 'All'} workloads in {location}:",
            items=items,
        )

    return _build_error_response(
        question=question,
        message="Unsupported resource listing type.",
        intent_result=intent_result,
        confidence="Low",
    )


def _process_pod_investigation(
    question: str,
    intent_result: Dict[str, Any],
    deep: bool = False,
) -> Dict[str, Any]:
    resource_name = intent_result.get("resource_name", "")
    namespace_hint = intent_result.get("namespace", "")

    if not resource_name:
        return _build_ambiguous_intent_response(question, intent_result)

    if namespace_hint:
        namespace_validation_result = get_pods(namespace_hint)
        if not namespace_validation_result.get("success", False):
            suggestions = _closest_matches(namespace_hint, _get_all_namespaces_from_cluster(), limit=2, cutoff=0.65)
            suggestion_text = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""

            return _build_error_response(
                question=question,
                message=namespace_validation_result.get(
                    "error",
                    f"Namespace '{namespace_hint}' does not exist or pods could not be fetched."
                ) + suggestion_text,
                intent_result=intent_result,
                resource=namespace_hint,
                resource_type="Namespace",
                confidence="High" if suggestions else "Medium",
            )

    cluster_pods_result = get_cluster_pods()
    if not cluster_pods_result.get("success", False):
        return _build_error_response(
            question=question,
            message=cluster_pods_result.get("error", "Failed to get cluster pod information."),
            intent_result=intent_result,
            resource=resource_name,
            resource_type="Workload",
            confidence="Low",
        )

    cluster_pods = ((cluster_pods_result.get("data") or {}).get("items")) or []
    matched_pods = _match_workload_pods(cluster_pods, resource_name, namespace_hint=namespace_hint)

    if not matched_pods:
        suggestions = _closest_matches(
            resource_name,
            _get_all_workload_candidates_from_cluster(namespace_hint=namespace_hint),
        )
        suggestion_text = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""

        namespace_text = f" in namespace '{namespace_hint}'" if namespace_hint else ""

        return _build_error_response(
            question=question,
            message=f"No matching pods found for workload '{resource_name}'{namespace_text} in the cluster.{suggestion_text}",
            intent_result=intent_result,
            resource=resource_name,
            resource_type="Workload",
            confidence="High" if suggestions else "Medium",
        )

    pod_health_results = [check_pod_health(pod) for pod in matched_pods]
    healthy_pods, unhealthy_pods = _summarize_pod_health_results(pod_health_results)

    total_count = len(matched_pods)
    healthy_count = len(healthy_pods)
    unhealthy_count = len(unhealthy_pods)

    response = _build_base_response(
        question=question,
        intent_result=intent_result,
        resource=resource_name,
        resource_type="Workload",
    )

    if unhealthy_count == 0:
        namespace_text = f" in namespace '{namespace_hint}'" if namespace_hint else ""
        response.update(
            {
                "status": "Healthy",
                "health_score": 100,
                "summary": (
                    f"Workload '{resource_name}'{namespace_text} is healthy. "
                    f"Matched pods: {total_count}, healthy: {healthy_count}, unhealthy: {unhealthy_count}."
                ),
                "confidence": "High",
            }
        )
        return response

    namespace_text = f" in namespace '{namespace_hint}'" if namespace_hint else ""
    summary = (
        f"Workload '{resource_name}'{namespace_text} is unhealthy. "
        f"Matched pods: {total_count}, healthy: {healthy_count}, unhealthy: {unhealthy_count}."
    )
    raw_evidence = _build_pod_issue_evidence(unhealthy_pods)
    health_score = max(0, int((healthy_count / total_count) * 100))
    recommendations = _basic_investigation_recommendations(unhealthy_pods, resource_name=resource_name)

    response.update(
        {
            "status": "Unhealthy",
            "health_score": health_score,
            "summary": summary,
            "evidence": raw_evidence,
            "confidence": "High",
            "recommendations": recommendations,
        }
    )

    if deep:
        deep_result = _maybe_run_deep_rca(
            question=question,
            resource_name=resource_name,
            namespace_hint=namespace_hint,
            matched_pods=matched_pods,
            unhealthy_results=unhealthy_pods,
        )
        response["root_cause"] = deep_result.get("root_cause", "")
        response["recommendations"] = deep_result.get("recommendations", recommendations)
        if deep_result.get("confidence"):
            response["confidence"] = deep_result["confidence"]

        response["evidence"] = _append_ai_evidence(
            raw_evidence=raw_evidence,
            category=deep_result.get("category", ""),
            evidence_summary=deep_result.get("evidence", ""),
            evidence_points=deep_result.get("evidence_points", []),
        )

    return response


def _process_namespace_health(question: str, intent_result: Dict[str, Any]) -> Dict[str, Any]:
    namespace = intent_result.get("resource_name", "")
    if not namespace:
        return _build_ambiguous_intent_response(question, intent_result)

    pods_result = get_pods(namespace)
    if not pods_result.get("success", False):
        suggestions = _closest_matches(namespace, _get_all_namespaces_from_cluster(), limit=2, cutoff=0.65)
        suggestion_text = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""

        return _build_error_response(
            question=question,
            message=pods_result.get(
                "error",
                f"Namespace '{namespace}' does not exist or pods could not be fetched."
            ) + suggestion_text,
            intent_result=intent_result,
            resource=namespace,
            resource_type="Namespace",
            confidence="High" if suggestions else "Medium",
        )

    pods = ((pods_result.get("data") or {}).get("items")) or []
    health_result = check_namespace_health(pods)

    response = _build_base_response(
        question=question,
        intent_result=intent_result,
        resource=namespace,
        resource_type="Namespace",
    )

    if health_result.get("healthy", False):
        response.update(
            {
                "status": "Healthy",
                "health_score": health_result.get("score", 100),
                "summary": f"Namespace '{namespace}' is healthy.",
                "confidence": "High",
            }
        )
        return response

    issues = health_result.get("issues", [])
    evidence = "\n".join(issues) if isinstance(issues, list) else str(issues)

    response.update(
        {
            "status": "Unhealthy",
            "health_score": health_result.get("score", 0),
            "summary": f"Namespace '{namespace}' is unhealthy.",
            "evidence": evidence,
            "confidence": "High",
            "recommendations": [
                "Inspect unhealthy pods in the namespace.",
                "Review pod events, restart counts, readiness, and referenced resources.",
                "Use a workload-specific prompt for deeper troubleshooting, for example: 'Why is bad-image failing?'",
            ],
        }
    )
    return response


def _build_cluster_recommendations(issues: List[Dict[str, Any]]) -> List[str]:
    recommendations: List[str] = []

    if not issues:
        return recommendations

    first_issue = issues[0]
    if isinstance(first_issue, dict):
        resource_type = first_issue.get("resource_type", "")
        resource_name = first_issue.get("resource_name", "")
        namespace = first_issue.get("namespace", "")
        status = first_issue.get("status", "")

        if resource_type == "Pod":
            if namespace:
                recommendations.append(
                    f"Investigate pod '{resource_name}' in namespace '{namespace}' because it is reporting '{status}'."
                )
                if "-" in resource_name:
                    workload_name = resource_name.rsplit("-", 2)[0] if resource_name.count("-") >= 2 else resource_name
                    recommendations.append(
                        f"Check the workload '{workload_name}' in namespace '{namespace}' to see whether other replicas are affected."
                    )
            else:
                recommendations.append(
                    f"Investigate pod '{resource_name}' because it is reporting '{status}'."
                )
        elif resource_type == "Node":
            recommendations.append(
                f"Investigate node '{resource_name}' because it is reporting '{status}'."
            )

    if not recommendations:
        recommendations.append("Investigate the unhealthy resources reported in the cluster.")

    return recommendations


def _process_cluster_health(question: str, intent_result: Dict[str, Any]) -> Dict[str, Any]:
    nodes_result = get_nodes()
    pods_result = get_cluster_pods()

    if not nodes_result.get("success", False):
        return _build_error_response(
            question=question,
            message=nodes_result.get("error", "Failed to get node information."),
            intent_result=intent_result,
            resource="cluster",
            resource_type="Cluster",
            confidence="Low",
        )

    if not pods_result.get("success", False):
        return _build_error_response(
            question=question,
            message=pods_result.get("error", "Failed to get cluster pod information."),
            intent_result=intent_result,
            resource="cluster",
            resource_type="Cluster",
            confidence="Low",
        )

    nodes = ((nodes_result.get("data") or {}).get("items")) or []
    pods = ((pods_result.get("data") or {}).get("items")) or []

    cluster_data = {
        "nodes": nodes,
        "pods": pods,
        "events": [],
        "node_metrics": {},
        "pod_metrics": {},
    }

    health_result = check_cluster_health(cluster_data)

    response = _build_base_response(
        question=question,
        intent_result=intent_result,
        resource="cluster",
        resource_type="Cluster",
    )

    if health_result.get("healthy", False):
        response.update(
            {
                "status": "Healthy",
                "health_score": health_result.get("score", 100),
                "summary": health_result.get("summary", "Cluster is healthy."),
                "confidence": "High",
            }
        )
        return response

    issues = health_result.get("issues", [])
    evidence_lines: List[str] = []

    for issue in issues:
        if isinstance(issue, dict):
            resource_type = issue.get("resource_type", "Resource")
            resource_name = issue.get("resource_name", "unknown")
            namespace = issue.get("namespace", "")
            status = issue.get("status", "Unknown")
            prefix = f"{namespace}/" if namespace else ""
            evidence_lines.append(f"{resource_type} {prefix}{resource_name}: {status}")
        else:
            evidence_lines.append(str(issue))

    response.update(
        {
            "status": "Unhealthy",
            "health_score": health_result.get("score", 0),
            "summary": health_result.get("summary", "Cluster is unhealthy."),
            "evidence": "\n".join(evidence_lines),
            "confidence": "High" if issues else "Medium",
            "recommendations": _build_cluster_recommendations(issues),
        }
    )
    return response


def process_question(question: str) -> Dict[str, Any]:
    try:
        intent_result = classify_intent(question)
    except Exception as exc:
        return _build_error_response(
            question=question,
            message=f"Failed to classify intent: {str(exc)}",
            confidence="Low",
        )

    if intent_result.get("intent_clarity") == "ambiguous":
        return _build_ambiguous_intent_response(question, intent_result)

    intent = intent_result.get("intent", "")
    if not intent:
        return _build_ambiguous_intent_response(question, intent_result)

    if intent == "Help":
        return _process_help(question, intent_result)

    if intent == "UnsupportedAction":
        return _process_unsupported_action(question, intent_result)

    if intent == "ResourceListing":
        return _process_resource_listing(question, intent_result)

    if intent == "PodInvestigation":
        return _process_pod_investigation(question, intent_result, deep=False)

    if intent == "DeepPodInvestigation":
        return _process_pod_investigation(question, intent_result, deep=True)

    if intent == "NamespaceHealth":
        return _process_namespace_health(question, intent_result)

    if intent == "ClusterHealth":
        return _process_cluster_health(question, intent_result)

    return _build_error_response(
        question=question,
        message=f"Unsupported intent '{intent}'.",
        intent_result=intent_result,
        confidence="Low",
    )
