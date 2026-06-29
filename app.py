import time
from datetime import datetime

import streamlit as st

from controller import process_question


APP_NAME = "KubeSage"
APP_TAGLINE = "Kubernetes Troubleshooting & RCA Assistant"


def is_deep_request(question: str) -> bool:
    q = (question or "").lower()
    markers = [
        "deep",
        "detailed",
        "root cause",
        "rca",
        "perform rca",
        "do rca",
        "run rca",
    ]
    return any(marker in q for marker in markers)


def render_page_setup():
    st.set_page_config(
        page_title=APP_NAME,
        page_icon="🧠",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def render_custom_css():
    st.markdown(
        """
        <style>
        .main-title {
            font-size: 2.2rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
            color: #1f2937;
        }
        .sub-title {
            font-size: 1.05rem;
            color: #4b5563;
            margin-bottom: 1.2rem;
        }
        .status-card {
            padding: 1rem 1.2rem;
            border-radius: 0.8rem;
            background: #f8fafc;
            border: 1px solid #e5e7eb;
            margin-bottom: 1rem;
        }
        .section-title {
            font-size: 1.1rem;
            font-weight: 600;
            margin-top: 0.4rem;
            margin-bottom: 0.5rem;
            color: #111827;
        }
        .small-muted {
            color: #6b7280;
            font-size: 0.92rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header():
    st.markdown(
        f"""
        <div class="main-title">🧠 {APP_NAME}</div>
        <div class="sub-title">{APP_TAGLINE}</div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar():
    with st.sidebar:
        st.markdown("## KubeSage")
        st.write(
            "Investigate Kubernetes health issues, pod failures, namespace problems, "
            "and deep root cause analysis requests."
        )

        st.markdown("### Example prompts")
        examples = [
            "show cluster health",
            "how is namespace ai-investigator-lab",
            "investigate bad-image",
            "show unhealthy workloads in ai-investigator-lab",
            "deep analyze dns-fail-loop",
            "perform rca on missing-configmap",
        ]
        for example in examples:
            st.code(example, language=None)

        st.markdown("### Guidance")
        st.info(
            "Use deep RCA prompts when you want richer investigation. "
            "These may take longer because KubeSage gathers pod evidence and runs AI analysis."
        )

        st.markdown("### Supported areas")
        st.write(
            "- Cluster health\n"
            "- Namespace health\n"
            "- Workload investigation\n"
            "- Resource listing\n"
            "- Deep RCA\n"
            "- Read-only troubleshooting"
        )


def render_summary_metrics(duration_seconds: float, started_at: str, request_type: str):
    col1, col2, col3 = st.columns(3)
    col1.metric("Started", started_at)
    col2.metric("Duration (s)", f"{duration_seconds:.2f}")
    col3.metric("Request Type", request_type)


def split_sections(text: str):
    lines = text.splitlines()

    preamble = []
    evidence = []
    recommendations = []

    section = "preamble"

    for line in lines:
        stripped = line.strip()

        if stripped == "Evidence:":
            section = "evidence"
            continue
        if stripped == "Recommended next steps:":
            section = "recommendations"
            continue

        if section == "preamble":
            preamble.append(line)
        elif section == "evidence":
            evidence.append(line)
        elif section == "recommendations":
            recommendations.append(line)

    return (
        "\n".join(preamble).strip(),
        "\n".join(evidence).strip(),
        "\n".join(recommendations).strip(),
    )


def render_pretty_output(result):
    if isinstance(result, dict):
        if "response" in result:
            output_text = str(result["response"])
        else:
            st.markdown("### Structured output")
            st.json(result)
            return
    else:
        output_text = str(result)

    if not output_text.strip():
        st.warning("No output returned.")
        return

    preamble, evidence, recommendations = split_sections(output_text)

    st.markdown('<div class="section-title">Result</div>', unsafe_allow_html=True)
    if preamble:
        st.code(preamble, language=None)
    else:
        st.info("No summary section returned.")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown('<div class="section-title">Evidence</div>', unsafe_allow_html=True)
        if evidence:
            st.code(evidence, language=None)
        else:
            st.info("No evidence section returned.")

    with col2:
        st.markdown('<div class="section-title">Recommended next steps</div>', unsafe_allow_html=True)
        if recommendations:
            st.code(recommendations, language=None)
        else:
            st.info("No recommendation section returned.")

    with st.expander("Raw output"):
        if isinstance(result, dict):
            st.json(result)
        else:
            st.code(output_text, language=None)


def main():
    render_page_setup()
    render_custom_css()
    render_header()
    render_sidebar()

    st.markdown(
        """
        <div class="status-card">
            Ask a Kubernetes troubleshooting question in natural language.
            Examples: cluster health, namespace health, workload investigation,
            unhealthy resource listing, or deep root cause analysis.
        </div>
        """,
        unsafe_allow_html=True,
    )

    question = st.text_area(
        "Prompt",
        height=130,
        placeholder=(
            "Examples:\n"
            "- show cluster health\n"
            "- investigate missing-secret\n"
            "- deep analyze dns-fail-loop\n"
            "- perform rca on bad-image in ai-investigator-lab"
        ),
    )

    c1, c2, c3 = st.columns([1.2, 1.2, 4])
    run_clicked = c1.button("Run analysis", type="primary", use_container_width=True)
    clear_clicked = c2.button("Clear", use_container_width=True)

    if clear_clicked:
        st.rerun()

    if run_clicked:
        if not question.strip():
            st.warning("Please enter a prompt.")
            return

        request_type = "Deep RCA" if is_deep_request(question) else "Standard"
        if request_type == "Deep RCA":
            st.warning("Deep RCA detected. This request may take longer to complete.")

        started_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        start = time.time()

        with st.spinner("KubeSage is investigating the cluster state..."):
            try:
                result = process_question(question)
            except Exception as exc:
                st.error(f"Application error: {exc}")
                return

        duration = time.time() - start

        st.success("Analysis complete")
        render_summary_metrics(duration, started_at, request_type)
        render_pretty_output(result)


if __name__ == "__main__":
    main()