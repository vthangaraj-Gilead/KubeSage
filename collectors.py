import json
import subprocess
from typing import Any, Dict, List


def run_command(command: str) -> Dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            check=True,
        )
        return {
            "success": True,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "stdout": e.stdout.strip() if e.stdout else "",
            "stderr": e.stderr.strip() if e.stderr else f"Command failed with exit code {e.returncode}",
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Error: {str(e)}",
        }


def namespace_exists(namespace: str) -> bool:
    command = f"kubectl get namespace {namespace} -o json"
    result = run_command(command)
    return result["success"]


def _run_kubectl_json(command: str, namespace: str = "") -> Dict[str, Any]:
    if namespace and not namespace_exists(namespace):
        return {
            "success": False,
            "command": command,
            "data": None,
            "error": f"Namespace '{namespace}' does not exist",
        }

    result = run_command(command)

    if not result["success"]:
        return {
            "success": False,
            "command": command,
            "data": None,
            "error": result["stderr"],
        }

    try:
        parsed = json.loads(result["stdout"])
        items = parsed.get("items", [])

        return {
            "success": True,
            "command": command,
            "data": parsed,
            "message": "No resources found" if isinstance(items, list) and len(items) == 0 else "Resources fetched successfully",
            "error": "",
        }
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "command": command,
            "data": None,
            "error": f"Failed to parse JSON: {str(e)}",
        }


def _parse_top_output(stdout: str, namespaced: bool = False) -> List[Dict[str, str]]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]

    if len(lines) <= 1:
        return []

    data_lines = lines[1:]
    parsed_rows: List[Dict[str, str]] = []

    for line in data_lines:
        parts = line.split()

        if namespaced:
            if len(parts) < 4:
                continue
            parsed_rows.append(
                {
                    "namespace": parts[0],
                    "name": parts[1],
                    "cpu": parts[2],
                    "memory": parts[3],
                }
            )
        else:
            if len(parts) < 3:
                continue
            parsed_rows.append(
                {
                    "name": parts[0],
                    "cpu": parts[1],
                    "memory": parts[2],
                }
            )

    return parsed_rows


def _run_kubectl_top(command: str, namespace: str = "", namespaced: bool = False) -> Dict[str, Any]:
    if namespace and not namespace_exists(namespace):
        return {
            "success": False,
            "command": command,
            "data": None,
            "error": f"Namespace '{namespace}' does not exist",
        }

    result = run_command(command)

    if not result["success"]:
        error_text = result["stderr"] or result["stdout"]

        if "metrics api not available" in error_text.lower() or "metrics server" in error_text.lower():
            return {
                "success": False,
                "command": command,
                "available": False,
                "data": None,
                "message": "Metrics Server is not installed.",
                "error": error_text,
            }

        return {
            "success": False,
            "command": command,
            "available": True,
            "data": None,
            "error": error_text,
        }

    parsed_items = _parse_top_output(result["stdout"], namespaced=namespaced)

    return {
        "success": True,
        "command": command,
        "available": True,
        "data": {
            "items": parsed_items,
        },
        "message": "No resources found" if len(parsed_items) == 0 else "Resources fetched successfully",
        "error": "",
    }


def get_pods(namespace: str) -> Dict[str, Any]:
    command = f"kubectl get pods -n {namespace} -o json"
    return _run_kubectl_json(command, namespace)


def get_events(namespace: str) -> Dict[str, Any]:
    command = f"kubectl get events -n {namespace} -o json"
    return _run_kubectl_json(command, namespace)


def get_deployments(namespace: str) -> Dict[str, Any]:
    command = f"kubectl get deployments -n {namespace} -o json"
    return _run_kubectl_json(command, namespace)


def get_pvc(namespace: str) -> Dict[str, Any]:
    command = f"kubectl get pvc -n {namespace} -o json"
    return _run_kubectl_json(command, namespace)


def get_nodes() -> Dict[str, Any]:
    command = "kubectl get nodes -o json"
    return _run_kubectl_json(command)


def get_cluster_pods() -> Dict[str, Any]:
    command = "kubectl get pods -A -o json"
    return _run_kubectl_json(command)


def get_node_metrics() -> Dict[str, Any]:
    """
    Collect CPU and memory utilization for all nodes using kubectl top nodes.
    Returns a structured dictionary and gracefully handles missing Metrics Server.
    """
    command = "kubectl top nodes"
    return _run_kubectl_top(command)


def get_pod_metrics(namespace: str) -> Dict[str, Any]:
    """
    Collect CPU and memory utilization for all pods in a namespace using kubectl top pods.
    Returns a structured dictionary and handles empty namespaces gracefully.
    """
    command = f"kubectl top pods -n {namespace}"
    return _run_kubectl_top(command, namespace=namespace)


def get_cluster_pod_metrics() -> Dict[str, Any]:
    """
    Collect CPU and memory utilization for all pods in the cluster using kubectl top pods -A.
    Returns a structured dictionary.
    """
    command = "kubectl top pods -A"
    return _run_kubectl_top(command, namespaced=True)
