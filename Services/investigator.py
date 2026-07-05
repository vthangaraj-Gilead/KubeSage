from typing import Dict

from collectors import run_command


def investigate_pod(namespace: str, pod_name: str) -> Dict[str, str]:
    describe_cmd = f"kubectl describe pod {pod_name} -n {namespace}"
    logs_cmd = f"kubectl logs {pod_name} -n {namespace} --tail=40"
    previous_logs_cmd = f"kubectl logs {pod_name} -n {namespace} --previous --tail=60"
    events_cmd = f"kubectl get events -n {namespace} --field-selector involvedObject.name={pod_name}"
    pvc_cmd = f"kubectl get pvc -n {namespace}"

    describe_result = run_command(describe_cmd)
    logs_result = run_command(logs_cmd)
    previous_logs_result = run_command(previous_logs_cmd)
    events_result = run_command(events_cmd)
    pvc_result = run_command(pvc_cmd)

    return {
        "pod": pod_name,
        "describe": describe_result.get("stdout", "") if describe_result.get("success") else describe_result.get("stderr", ""),
        "logs": logs_result.get("stdout", "") if logs_result.get("success") else logs_result.get("stderr", ""),
        "previous_logs": previous_logs_result.get("stdout", "") if previous_logs_result.get("success") else previous_logs_result.get("stderr", ""),
        "events": events_result.get("stdout", "") if events_result.get("success") else events_result.get("stderr", ""),
        "pvc": pvc_result.get("stdout", "") if pvc_result.get("success") else pvc_result.get("stderr", ""),
    }
