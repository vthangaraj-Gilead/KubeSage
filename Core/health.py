from typing import Any, Dict, List


HEALTHY_POD_PHASES = {"Running", "Succeeded", "Completed"}
UNHEALTHY_WAITING_REASONS = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerError",
    "CreateContainerConfigError",
}
UNHEALTHY_TERMINATION_REASONS = {
    "Error",
    "OOMKilled",
    "Evicted",
}


def _get_ready_condition(status: Dict[str, Any]) -> str:
    conditions = status.get("conditions", []) or []
    for condition in conditions:
        if condition.get("type") == "Ready":
            return str(condition.get("status", "Unknown"))
    return "Unknown"


def _is_completed_successfully(status: Dict[str, Any]) -> bool:
    phase = str(status.get("phase", "Unknown"))
    container_statuses = status.get("containerStatuses", []) or []

    if phase == "Succeeded":
        return True

    if not container_statuses:
        return False

    all_terminated_successfully = True

    for container in container_statuses:
        state = container.get("state", {}) or {}
        waiting = state.get("waiting")
        terminated = state.get("terminated")

        if waiting is not None:
            return False

        if not terminated:
            all_terminated_successfully = False
            continue

        exit_code = int(terminated.get("exitCode", 1) or 1)
        reason = str(terminated.get("reason", "") or "")

        if exit_code != 0 and reason not in {"Completed"}:
            return False

    return all_terminated_successfully


def check_pod_health(pod: Dict[str, Any]) -> Dict[str, Any]:
    metadata = pod.get("metadata", {})
    status = pod.get("status", {})
    container_statuses = status.get("containerStatuses", []) or []

    pod_name = metadata.get("name", "unknown")
    namespace = metadata.get("namespace", "default")
    phase = status.get("phase", "Unknown")
    ready_condition = _get_ready_condition(status)

    if _is_completed_successfully(status):
        return {
            "healthy": True,
            "pod_name": pod_name,
            "namespace": namespace,
            "phase": phase,
            "issues": [],
        }

    issues: List[str] = []

    if phase not in HEALTHY_POD_PHASES:
        issues.append(f"Pod phase is {phase}")

    if phase == "Running" and ready_condition == "False":
        issues.append("Pod is Running but NotReady")

    for container in container_statuses:
        state = container.get("state", {}) or {}
        last_state = container.get("lastState", {}) or {}
        waiting = state.get("waiting")
        terminated = state.get("terminated")
        last_terminated = last_state.get("terminated")
        restart_count = int(container.get("restartCount", 0) or 0)
        ready = bool(container.get("ready", False))
        name = container.get("name", "container")

        if waiting:
            reason = str(waiting.get("reason", "Unknown"))
            if reason not in {"ContainerCreating", "PodInitializing"}:
                issues.append(f"Container waiting: {reason}")

        if terminated:
            reason = str(terminated.get("reason", "Unknown"))
            exit_code = int(terminated.get("exitCode", 0) or 0)

            if exit_code != 0 or reason in UNHEALTHY_TERMINATION_REASONS:
                issues.append(f"Container terminated: {reason} (exitCode={exit_code})")
            elif restart_count > 0 and phase != "Succeeded":
                issues.append(f"Container restarted after exitCode=0 ({name})")

        if last_terminated:
            last_reason = str(last_terminated.get("reason", "Unknown"))
            last_exit_code = int(last_terminated.get("exitCode", 0) or 0)

            currently_unhealthy = (
                phase not in HEALTHY_POD_PHASES
                or ready_condition == "False"
                or waiting is not None
                or terminated is not None
                or (phase == "Running" and not ready)
            )

            if last_reason.lower() == "oomkilled" and currently_unhealthy:
                issues.append("Container terminated: OOMKilled")

            if restart_count > 0 and last_exit_code != 0 and currently_unhealthy:
                issues.append(f"Container last terminated: {last_reason} (exitCode={last_exit_code})")

            if restart_count > 0 and last_exit_code == 0 and not ready and phase == "Running":
                issues.append(f"Container repeatedly restarting after exitCode=0 ({name})")

        if restart_count > 0 and not ready and not waiting and not terminated and phase == "Running":
            issues.append(f"Container restart count is high or non-zero: {restart_count}")

    deduped_issues: List[str] = []
    seen = set()
    for issue in issues:
        if issue not in seen:
            deduped_issues.append(issue)
            seen.add(issue)

    healthy = len(deduped_issues) == 0

    return {
        "healthy": healthy,
        "pod_name": pod_name,
        "namespace": namespace,
        "phase": phase,
        "issues": deduped_issues,
    }


def check_namespace_health(pods: List[Dict[str, Any]]) -> Dict[str, Any]:
    unhealthy_pods: List[Dict[str, Any]] = []
    healthy_pods: List[Dict[str, Any]] = []

    for pod in pods:
        result = check_pod_health(pod)
        if result["healthy"]:
            healthy_pods.append(result)
        else:
            unhealthy_pods.append(result)

    total = len(pods)
    unhealthy_count = len(unhealthy_pods)

    if total == 0:
        score = 100
    else:
        score = max(0, int(((total - unhealthy_count) / total) * 100))

    healthy = unhealthy_count == 0

    issues: List[str] = []
    for pod in unhealthy_pods:
        issues.extend([f"{pod['pod_name']}: {issue}" for issue in pod["issues"]])

    return {
        "healthy": healthy,
        "score": score,
        "total_pods": total,
        "healthy_pods": healthy_pods,
        "unhealthy_pods": unhealthy_pods,
        "issues": issues,
    }


def _classify_pod_issue(pod_issues: List[str]) -> Dict[str, Any]:
    dominant_status = None
    dominant_penalty = 0
    dominant_severity = "warning"

    for issue_text in pod_issues:
        normalized = issue_text.lower()

        if "crashloopbackoff" in normalized:
            dominant_status = "CrashLoopBackOff"
            dominant_penalty = 15
            dominant_severity = "critical"
            break
        elif "imagepullbackoff" in normalized:
            if dominant_penalty < 15:
                dominant_status = "ImagePullBackOff"
                dominant_penalty = 15
                dominant_severity = "critical"
        elif "errimagepull" in normalized:
            if dominant_penalty < 15:
                dominant_status = "ErrImagePull"
                dominant_penalty = 15
                dominant_severity = "critical"
        elif "createcontainererror" in normalized or "createcontainerconfigerror" in normalized:
            if dominant_penalty < 15:
                dominant_status = "CreateContainerError"
                dominant_penalty = 15
                dominant_severity = "critical"
        elif "oomkilled" in normalized:
            if dominant_penalty < 10:
                dominant_status = "OOMKilled"
                dominant_penalty = 10
                dominant_severity = "warning"
        elif "pod phase is pending" in normalized:
            if dominant_penalty < 5:
                dominant_status = "Pending"
                dominant_penalty = 5
                dominant_severity = "warning"
        elif "evicted" in normalized:
            if dominant_penalty < 5:
                dominant_status = "Evicted"
                dominant_penalty = 5
                dominant_severity = "warning"
        elif "terminated: error" in normalized:
            if dominant_penalty < 5:
                dominant_status = "Error"
                dominant_penalty = 5
                dominant_severity = "warning"
        elif "running but notready" in normalized or "notready" in normalized:
            if dominant_penalty < 5:
                dominant_status = "NotReady"
                dominant_penalty = 5
                dominant_severity = "warning"

    if dominant_status is None:
        dominant_status = pod_issues[0] if pod_issues else "Unhealthy"
        dominant_penalty = 5
        dominant_severity = "warning"

    return {
        "status": dominant_status,
        "penalty": dominant_penalty,
        "severity": dominant_severity,
    }


def check_cluster_health(cluster_data: Dict[str, Any]) -> Dict[str, Any]:
    nodes = cluster_data.get("nodes", []) or []
    pods = cluster_data.get("pods", []) or []
    pvcs = cluster_data.get("pvcs", []) or []
    events = cluster_data.get("events", []) or []
    node_metrics = cluster_data.get("node_metrics", {}) or {}
    pod_metrics = cluster_data.get("pod_metrics", {}) or {}

    score = 100
    issues: List[Dict[str, Any]] = []
    critical_count = 0
    warning_count = 0

    node_metric_map: Dict[str, Dict[str, Any]] = {}
    pod_metric_map: Dict[str, Dict[str, Any]] = {}

    node_metric_items = ((node_metrics.get("data") or {}).get("items")) or []
    for item in node_metric_items:
        name = item.get("name", "")
        if name:
            node_metric_map[name] = item

    pod_metric_items = ((pod_metrics.get("data") or {}).get("items")) or []
    for item in pod_metric_items:
        namespace = item.get("namespace", "")
        name = item.get("name", "")
        if namespace and name:
            pod_metric_map[f"{namespace}/{name}"] = item

    def add_issue(
        resource_type: str,
        resource_name: str,
        status: str,
        namespace: str = "",
        penalty: int = 0,
        severity: str = "warning",
    ) -> None:
        nonlocal score, critical_count, warning_count

        issue: Dict[str, Any] = {
            "resource_type": resource_type,
            "resource_name": resource_name,
            "status": status,
        }
        if namespace:
            issue["namespace"] = namespace

        issues.append(issue)

        if penalty > 0:
            score -= penalty

        if severity == "critical":
            critical_count += 1
        else:
            warning_count += 1

    def add_issue_without_penalty(
        resource_type: str,
        resource_name: str,
        status: str,
        namespace: str = "",
        severity: str = "warning",
    ) -> None:
        nonlocal critical_count, warning_count

        issue: Dict[str, Any] = {
            "resource_type": resource_type,
            "resource_name": resource_name,
            "status": status,
        }
        if namespace:
            issue["namespace"] = namespace

        issues.append(issue)

        if severity == "critical":
            critical_count += 1
        else:
            warning_count += 1

    for node in nodes:
        metadata = node.get("metadata", {}) or {}
        status = node.get("status", {}) or {}
        node_name = metadata.get("name", "unknown")

        conditions = status.get("conditions", []) or []
        condition_map = {
            condition.get("type"): condition.get("status")
            for condition in conditions
        }

        if condition_map.get("Ready") != "True":
            add_issue(
                resource_type="Node",
                resource_name=node_name,
                status="NotReady",
                penalty=25,
                severity="critical",
            )

        metric = node_metric_map.get(node_name)
        if metric:
            cpu_percent_value = str(metric.get("cpu_percent", "")).replace("%", "").strip()
            memory_percent_value = str(metric.get("memory_percent", "")).replace("%", "").strip()

            try:
                cpu_percent = int(cpu_percent_value)
                if cpu_percent > 90:
                    add_issue(
                        resource_type="Node",
                        resource_name=node_name,
                        status=f"HighCPU({cpu_percent}%)",
                        penalty=5,
                        severity="warning",
                    )
            except Exception:
                pass

            try:
                memory_percent = int(memory_percent_value)
                if memory_percent > 90:
                    add_issue(
                        resource_type="Node",
                        resource_name=node_name,
                        status=f"HighMemory({memory_percent}%)",
                        penalty=5,
                        severity="warning",
                    )
            except Exception:
                pass

    for pvc in pvcs:
        metadata = pvc.get("metadata", {}) or {}
        status = pvc.get("status", {}) or {}

        pvc_name = metadata.get("name", "unknown")
        namespace = metadata.get("namespace", "default")
        phase = status.get("phase", "Unknown")

        if phase == "Pending":
            add_issue(
                resource_type="PVC",
                resource_name=pvc_name,
                namespace=namespace,
                status="Pending",
                penalty=5,
                severity="warning",
            )

    total_pods = len(pods)
    unhealthy_pod_count = 0
    raw_pod_penalty = 0

    for pod in pods:
        pod_health = check_pod_health(pod)

        metadata = pod.get("metadata", {}) or {}
        pod_name = metadata.get("name", "unknown")
        namespace = metadata.get("namespace", "default")

        if pod_health.get("healthy", False):
            pod_metric = pod_metric_map.get(f"{namespace}/{pod_name}")

            if pod_metric and pod_health.get("phase") == "Running":
                cpu_value = str(pod_metric.get("cpu", "")).strip().lower()
                memory_value = str(pod_metric.get("memory", "")).strip().lower()

                try:
                    if cpu_value.endswith("m"):
                        cpu_millicores = int(cpu_value[:-1])
                        if cpu_millicores > 1000:
                            add_issue_without_penalty(
                                resource_type="Pod",
                                resource_name=pod_name,
                                namespace=namespace,
                                status=f"HighCPU({cpu_value})",
                                severity="warning",
                            )
                except Exception:
                    pass

                try:
                    if memory_value.endswith("mi"):
                        memory_mib = int(memory_value[:-2])
                        if memory_mib > 1024:
                            add_issue_without_penalty(
                                resource_type="Pod",
                                resource_name=pod_name,
                                namespace=namespace,
                                status=f"HighMemory({memory_value})",
                                severity="warning",
                            )
                except Exception:
                    pass

            continue

        unhealthy_pod_count += 1
        pod_issues = pod_health.get("issues", []) or []
        classified = _classify_pod_issue(pod_issues)

        add_issue_without_penalty(
            resource_type="Pod",
            resource_name=pod_name,
            status=classified["status"],
            namespace=namespace,
            severity=classified["severity"],
        )
        raw_pod_penalty += int(classified["penalty"])

    if total_pods > 0 and unhealthy_pod_count > 0 and raw_pod_penalty > 0:
        unhealthy_ratio = unhealthy_pod_count / total_pods
        scaled_pod_penalty = max(1, int(raw_pod_penalty * unhealthy_ratio))
        score -= scaled_pod_penalty

    warning_events = 0
    for event in events:
        event_type = (event.get("type") or "").strip()
        if event_type == "Warning":
            warning_events += 1

    event_penalty = min(warning_events, 10)
    score -= event_penalty

    if warning_events > 0:
        warning_count += warning_events

    if score < 0:
        score = 0

    healthy = len(issues) == 0

    if score >= 90:
        summary = "Cluster is healthy."
    elif score >= 70:
        summary = "Cluster is degraded."
    else:
        summary = "Cluster is unhealthy."

    return {
        "healthy": healthy,
        "score": score,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "issues": issues,
        "summary": summary,
    }