# KubeSage

KubeSage is a simple Kubernetes troubleshooting assistant. It helps users ask questions about cluster health, namespace health, pods, and workloads using either a small UI or the command line.

See the architecture flow: [Docs/Architecture.md](Docs/Architecture.md)

## 🔎 What it is

KubeSage is a lightweight troubleshooting layer on top of Kubernetes cluster data. It takes a user question, classifies the intent, gathers the relevant cluster information, checks health, and returns a short, readable answer.

It is meant to help users quickly understand what is unhealthy and where to investigate next.

## ⚙️ What it does

KubeSage can:

- check overall cluster health
- check namespace health
- investigate a pod or workload
- list healthy or unhealthy pods and workloads
- perform deeper RCA-style analysis for workloads, namespaces, and the cluster
- return short recommendations based on detected issues

It is read-only and focused on diagnosis, not making changes.

## 🧰 Technologies involved

- **Python 3.11** for the main application logic
- **Streamlit** for the simple UI in `app.py`
- **Kubernetes data collection logic** in Python for pods, nodes, events, PVCs, and metrics
- **LLM-assisted summarization** in `llm.py` for deep analysis flows
- **Docker** for containerized execution
- **Kubernetes** for deployment and cluster-side execution

## 📁 Top-level files

- `app.py` - UI entrypoint for asking questions interactively
- `ask_controller.py` - command-line entrypoint to ask one question directly
- `controller.py` - main orchestration layer that routes requests to the correct logic
- `intent_classification.py` - classifies user prompts into supported intents and filters
- `collectors.py` - collects Kubernetes data such as pods, nodes, events, metrics, and PVCs
- `health.py` - evaluates health for pods, namespaces, and the cluster
- `investigator.py` - gathers deeper pod-level investigation details for RCA
- `llm.py` - optional AI-assisted summarization and deep analysis
- `help_text.py` - stores help/capability text shown to users
- `faulty_workloads.yaml` - sample faulty workloads for testing/troubleshooting scenarios
- `final_test_case_run_150.txt` - saved output or validation notes from test runs
- `requirements.txt` - Python dependencies
- `Dockerfile` - container build definition
- `README.md` - project overview and usage
- `K8s/` - Kubernetes-related supporting files/assets

## 🛠️ Installation

### Local setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Make sure your Kubernetes access is available through your local kubeconfig or in-cluster configuration, depending on how you run the app.

### Docker build

Build the image:

```bash
docker build -t kubesage:latest .
```

### Deploy in a Kubernetes cluster

The exact manifests may vary based on your environment, but the usual steps are:

1. Build the Docker image
2. Push the image to your container registry
3. Update your Kubernetes deployment manifest with the image
4. Apply the manifests to the cluster

Example flow:

```bash
docker build -t <your-registry>/kubesage:latest .
docker push <your-registry>/kubesage:latest
kubectl apply -f K8s/
```

If you are deploying the Streamlit UI in-cluster, expose it using a `Service` and optionally an `Ingress`.

Example verification steps:

```bash
kubectl get pods
kubectl get svc
kubectl logs <kubesage-pod-name>
```

### Kubernetes access / permissions

KubeSage needs read access to the cluster resources it inspects, such as:

- pods
- namespaces
- nodes
- events
- PVCs
- metrics, if available in the cluster

If running inside Kubernetes, you will typically provide this through a `ServiceAccount`, `Role` / `ClusterRole`, and corresponding bindings.

## ▶️ How to run

### Run via UI

Start the Streamlit UI:

```bash
streamlit run app.py
```

Then open the local URL shown by Streamlit in your browser.

Example questions:

- `how is my cluster?`
- `show unhealthy pods in chaos namespace`
- `perform rca on ai-investigator-lab namespace`

### Run via command line

You can also use `ask_controller.py` directly:

```bash
python3.11 ask_controller.py "show unhealthy workloads in chaos namespace"
```

More examples:

```bash
python3.11 ask_controller.py "how is my cluster?"
python3.11 ask_controller.py "show running pods in rstudioworkbench namespace"
python3.11 ask_controller.py "perform rca on chaos namespace"
```

## 🎥 KubeSage Demo

https://github.com/user-attachments/assets/d43b629e-c926-4b26-871a-2827098059b4

## ✅ Current capabilities

- cluster health summary
- namespace health summary
- pod and workload investigation
- healthy/unhealthy/running/pending resource listing
- deep analysis for workload, namespace, and cluster cases
- simple support for natural language variations and typo handling
- UI and CLI execution

## ⚠️ Current limitations

- read-only only; it does not restart, patch, delete, or fix resources
- some prompt handling is rule-based, so unusual phrasing may not always classify correctly
- deep analysis quality depends on available logs, events, and LLM setup
- workload grouping is heuristic-based using labels and pod naming patterns
- not a full replacement for direct `kubectl describe`, logs, or manual debugging

## 🚀 Future improvements

- support for more Kubernetes resources beyond current pod/workload-focused flows
- security audit support to detect overpermissive resources and risky configurations
- Prometheus integration for app-level diagnostics and metrics-based troubleshooting
- improve natural language handling for more prompt variations
- add proper automated tests for classifier and controller behavior
- add structured logging instead of temporary debug prints
- improve workload grouping using owner references instead of only names/labels
- add clearer docs for architecture and execution flow
