def get_help_text() -> str:
    return """K8s Investigator current capabilities:

1. Cluster health
   - Example: How is my cluster?
   - Example: show cluster health
   - Example: give me cluster health summary

2. Namespace health
   - Example: How is namespace kube-system?
   - Example: In kube-system are all pods healthy?
   - Example: show namespace health for ai-investigator-lab
   - Example: give me namespace status for ai-investigator-lab
   - Example: anything wrong in ai-investigator-lab

3. Workload / pod investigation
   - Example: Why is crashloop-demo failing?
   - Example: How is my rstudio-workbench in rstudioworkbench?
   - Example: how is bad-command
   - Example: investigate bad-image
   - Example: what happened to dns-fail-loop
   - Example: check missing-pvc health
   - Example: is readiness-probe-fail okay

4. Cause-oriented troubleshooting
   - Example: did oomkill-test get oomkilled
   - Example: does missing-secret have secret issue
   - Example: is configmap missing for missing-configmap
   - Example: does liveness-probe-fail have probe issue
   - Example: why is readiness-probe-fail not ready

5. Deep root cause analysis
   - Use deep mode when you want richer root cause analysis with AI-generated evidence summaries.
   - Example: deep analyze bad-image
   - Example: give me deep rca for missing-pvc
   - Example: detailed root cause for oomkill-test
   - Example: deep investigation for liveness-probe-fail

6. Namespace-scoped investigation
   - Validates namespace before checking workload health.
   - Suggests close matches for mistyped namespaces or workloads.

7. Resource listing
   - Show all pods in a namespace
   - Show running pods
   - Show pending pods
   - Show unhealthy pods
   - Show crashlooping pods
   - Show image pull backoff pods
   - Show unhealthy workloads

   Examples:
   - show pods in kube-system
   - show running pods in kube-system
   - show pending pods in kube-system
   - list crashlooping pods
   - show unhealthy workloads in chaos
   - which pods are unhealthy in ai-investigator-lab
   - which workloads are unhealthy in ai-investigator-lab
   - show image pull backoff pods in ai-investigator-lab
   - show crash looping pods in ai-investigator-lab

8. Fast troubleshooting guidance
   - For unhealthy workloads and namespaces, the app can provide:
     - summary
     - evidence
     - recommendations
     - next steps

Important limitation:
- This tool is read-only for investigation and status checks.
- It does not create, delete, patch, scale, restart, cordon, uncordon, drain, or automatically fix cluster resources.

Tips:
- Be specific when possible.
- Good prompts usually mention cluster, namespace, workload, or pod.
- Use deep analysis prompts when you want richer RCA beyond the default fast investigation.
- If the request is unclear, the app will ask for a clearer prompt."""
