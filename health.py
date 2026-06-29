from typing import Any, Dict, List


def _get_ready_condition(status: Dict[str, Any]) -> str:
    conditions = status.get("conditions", []) or []
    for condition in conditions:
        if condition.get("type") == "Ready":
            return str(condition.get("status", "Unknown"))
    return "Unknown"


def check_pod_health(pod: Dict[str, Any]) -> Dict[str, Any]:
    metadata = pod.get("metadata", {})
    status = pod.get("status", {})
    container_statuses = status.get("containerStatuses", []) or []

    pod_name = metadata.get("name", "unknown")
    namespace = metadata.get("namespace", "default")
    phase = status.get("phase", "Unknown")
    ready_condition = _get_ready_condition(status)

    issues: List[str] = []

    if phase not in {"Running", "Succeeded"}:
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
            reason = waiting.get("reason", "Unknown")
            if reason not in {"ContainerCreating", "PodInitializing"}:
                issues.append(f"Container waiting: {reason}")

        if terminated:
            reason = terminated.get("reason", "Unknown")
            exit_code = terminated.get("exitCode", 0)
            if exit_code != 0:
                issues.append(f"Container terminated: {reason} (exitCode={exit_code})")
            elif restart_count > 0:
                issues.append(f"Container restarted after exitCode=0 ({name})")

        if last_terminated:
            last_reason = last_terminated.get("reason", "Unknown")
            last_exit_code = last_terminated.get("exitCode", 0)

            currently_unhealthy = (
                phase not in {"Running", "Succeeded"}
                or ready_condition == "False"
                or waiting is not None
                or terminated is not None
                or not ready
            )

            if str(last_reason).lower() == "oomkilled" and currently_unhealthy:
                issues.append("Container terminated: OOMKilled")

            if restart_count > 0 and last_exit_code != 0 and currently_unhealthy:
                issues.append(f"Container last terminated: {last_reason} (exitCode={last_exit_code})")

            if restart_count > 0 and last_exit_code == 0 and not ready:
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


def check_cluster_health(cluster_data: Dict[str, Any]) -> Dict[str, Any]:
    nodes = cluster_data.get("nodes", []) or []
    pods = cluster_data.get("pods", []) or []
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

        if condition_map.get("MemoryPressure") == "True":
            add_issue(
                resource_type="Node",
                resource_name=node_name,
                status="MemoryPressure",
                penalty=15,
                severity="warning",
            )

        if condition_map.get("DiskPressure") == "True":
            add_issue(
                resource_type="Node",
                resource_name=node_name,
                status="DiskPressure",
                penalty=15,
                severity="warning",
            )

        if condition_map.get("PIDPressure") == "True":
            add_issue(
                resource_type="Node",
                resource_name=node_name,
                status="PIDPressure",
                severity="warning",
            )

        if condition_map.get("NetworkUnavailable") == "True":
            add_issue(
                resource_type="Node",
                resource_name=node_name,
                status="NetworkUnavailable",
                severity="warning",
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
                        severity="warning",
                    )
            except Exception:
                pass

    for pod in pods:
        pod_health = check_pod_health(pod)

        if pod_health.get("healthy", False):
            metadata = pod.get("metadata", {}) or {}
            pod_name = metadata.get("name", "unknown")
            namespace = metadata.get("namespace", "default")
            pod_metric = pod_metric_map.get(f"{namespace}/{pod_name}")

            if pod_metric:
                cpu_value = str(pod_metric.get("cpu", "")).strip().lower()
                memory_value = str(pod_metric.get("memory", "")).strip().lower()

                try:
                    if cpu_value.endswith("m"):
                        cpu_millicores = int(cpu_value[:-1])
                        if cpu_millicores > 1000:
                            add_issue(
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
                            add_issue(
                                resource_type="Pod",
                                resource_name=pod_name,
                                namespace=namespace,
                                status=f"HighMemory({memory_value})",
                                severity="warning",
                            )
                except Exception:
                    pass

            continue

        pod_name = pod_health.get("pod_name", "unknown")
        namespace = pod_health.get("namespace", "default")
        pod_issues = pod_health.get("issues", []) or []

        for issue_text in pod_issues:
            normalized = issue_text.lower()

            if "crashloopbackoff" in normalized:
                add_issue(
                    resource_type="Pod",
                    resource_name=pod_name,
                    status="CrashLoopBackOff",
                    namespace=namespace,
                    penalty=15,
                    severity="critical",
                )
            elif "pod phase is pending" in normalized:
                add_issue(
                    resource_type="Pod",
                    resource_name=pod_name,
                    status="Pending",
                    namespace=namespace,
                    penalty=10,
                    severity="warning",
                )
            elif "imagepullbackoff" in normalized:
                add_issue(
                    resource_type="Pod",
                    resource_name=pod_name,
                    status="ImagePullBackOff",
                    namespace=namespace,
                    penalty=10,
                    severity="warning",
                )
            elif "errimagepull" in normalized:
                add_issue(
                    resource_type="Pod",
                    resource_name=pod_name,
                    status="ErrImagePull",
                    namespace=namespace,
                    severity="warning",
                )
            elif "oomkilled" in normalized:
                add_issue(
                    resource_type="Pod",
                    resource_name=pod_name,
                    status="OOMKilled",
                    namespace=namespace,
                    penalty=10,
                    severity="warning",
                )
            elif "evicted" in normalized:
                add_issue(
                    resource_type="Pod",
                    resource_name=pod_name,
                    status="Evicted",
                    namespace=namespace,
                    severity="warning",
                )
            elif "createcontainererror" in normalized:
                add_issue(
                    resource_type="Pod",
                    resource_name=pod_name,
                    status="CreateContainerError",
                    namespace=namespace,
                    severity="warning",
                )
            elif "createcontainerconfigerror" in normalized:
                add_issue(
                    resource_type="Pod",
                    resource_name=pod_name,
                    status="CreateContainerConfigError",
                    namespace=namespace,
                    severity="warning",
                )
            elif "terminated: error" in normalized:
                add_issue(
                    resource_type="Pod",
                    resource_name=pod_name,
                    status="Error",
                    namespace=namespace,
                    severity="warning",
                )
            elif "running but notready" in normalized or "notready" in normalized:
                add_issue(
                    resource_type="Pod",
                    resource_name=pod_name,
                    status="NotReady",
                    namespace=namespace,
                    penalty=10,
                    severity="warning",
                )
            else:
                add_issue(
                    resource_type="Pod",
                    resource_name=pod_name,
                    status=issue_text,
                    namespace=namespace,
                    severity="warning",
                )

        pod_metric = pod_metric_map.get(f"{namespace}/{pod_name}")
        if pod_metric:
            cpu_value = str(pod_metric.get("cpu", "")).strip().lower()
            memory_value = str(pod_metric.get("memory", "")).strip().lower()

            try:
                if cpu_value.endswith("m"):
                    cpu_millicores = int(cpu_value[:-1])
                    if cpu_millicores > 1000:
                        add_issue(
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
                        add_issue(
                            resource_type="Pod",
                            resource_name=pod_name,
                            namespace=namespace,
                            status=f"HighMemory({memory_value})",
                            severity="warning",
                        )
            except Exception:
                pass

    warning_events = 0
    for event in events:
        event_type = (event.get("type") or "").strip()
        if event_type == "Warning":
            warning_events += 1

    event_penalty = min(warning_events * 2, 10)
    score -= event_penalty

    if warning_events > 0:
        warning_count += warning_events

    if score < 0:
        score = 0

    healthy = len(issues) == 0
    summary = "Cluster is healthy." if healthy else "Cluster is unhealthy."

    return {
        "healthy": healthy,
        "score": score,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "issues": issues,
        "summary": summary,
    }
