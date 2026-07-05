import html
import time
from datetime import datetime
from typing import Any, Dict, List

import streamlit as st

from Core.controller import process_question


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


def render_page_setup() -> None:
    st.set_page_config(
        page_title=APP_NAME,
        page_icon="🧠",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def render_custom_css() -> None:
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
        .hero-card {
            padding: 1rem 1.2rem;
            border-radius: 0.85rem;
            background: #f8fafc;
            border: 1px solid #e5e7eb;
            margin-bottom: 1rem;
        }
        .section-card {
            padding: 1rem 1rem;
            border-radius: 0.85rem;
            background: #ffffff;
            border: 1px solid #e5e7eb;
            margin-bottom: 1rem;
        }
        .section-title {
            font-size: 1.05rem;
            font-weight: 650;
            margin-bottom: 0.6rem;
            color: #111827;
        }
        .body-text {
            color: #1f2937;
            line-height: 1.55;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .kv-label {
            font-size: 0.85rem;
            color: #6b7280;
            margin-bottom: 0.15rem;
        }
        .kv-value {
            font-size: 0.98rem;
            color: #111827;
            font-weight: 500;
            margin-bottom: 0.7rem;
            word-break: break-word;
        }
        .bullet-list {
            margin: 0.2rem 0 0.2rem 1rem;
            padding-left: 0.8rem;
            color: #1f2937;
            line-height: 1.55;
        }
        .bullet-list li {
            margin-bottom: 0.45rem;
        }
        .root-cause-box {
            padding: 0.9rem 1rem;
            border-radius: 0.75rem;
            background: #fff7ed;
            border: 1px solid #fdba74;
            color: #9a3412;
            font-weight: 500;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .summary-box {
            padding: 0.9rem 1rem;
            border-radius: 0.75rem;
            background: #f9fafb;
            border: 1px solid #e5e7eb;
            color: #111827;
            white-space: pre-wrap;
            word-break: break-word;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.markdown(
        f"""
        <div class="main-title">🧠 {APP_NAME}</div>
        <div class="sub-title">{APP_TAGLINE}</div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## KubeSage")
        st.write(
            "Investigate Kubernetes health issues, pod failures, namespace problems, "
            "and deep root cause analysis requests."
        )

        st.markdown("### Example prompts")
        examples = [
            "show cluster health",
            "analyze my cluster",
            "deep analyze my cluster",
            "how is namespace ai-investigator-lab",
            "deep analyze ai-investigator-lab namespace",
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
            "These may take longer because KubeSage gathers evidence and runs AI analysis."
        )

        st.markdown("### Capabilities")
        st.write(
            "- Cluster health\n"
            "- Namespace health\n"
            "- Workload investigation\n"
            "- Resource listing\n"
            "- Deep RCA for cluster, namespace, and workload scopes\n"
            "- Read-only troubleshooting"
        )


def render_summary_metrics(duration_seconds: float, started_at: str, request_type: str) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Started", started_at)
    col2.metric("Duration (s)", f"{duration_seconds:.2f}")
    col3.metric("Request Type", request_type)


def _escape(text: Any) -> str:
    return html.escape("" if text is None else str(text))


def render_key_value_grid(result: Dict[str, Any]) -> None:
    question = result.get("question", "")
    intent = result.get("intent", "")
    resource = result.get("resource", "")
    resource_type = result.get("resource_type", "")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            f"""
            <div class="section-card">
                <div class="kv-label">Question</div>
                <div class="kv-value">{_escape(question or "N/A")}</div>
                <div class="kv-label">Intent</div>
                <div class="kv-value">{_escape(intent or "N/A")}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
            <div class="section-card">
                <div class="kv-label">Resource</div>
                <div class="kv-value">{_escape(resource or "N/A")}</div>
                <div class="kv-label">Resource Type</div>
                <div class="kv-value">{_escape(resource_type or "N/A")}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_text_block(title: str, text: str, use_summary_style: bool = False) -> None:
    css_class = "summary-box" if use_summary_style else "body-text"
    safe_text = _escape(text or "No details available.")
    st.markdown(
        f"""
        <div class="section-card">
            <div class="section-title">{_escape(title)}</div>
            <div class="{css_class}">{safe_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_root_cause(root_cause: str) -> None:
    safe_text = _escape(root_cause or "No root cause provided.")
    st.markdown(
        f"""
        <div class="section-card">
            <div class="section-title">Root cause</div>
            <div class="root-cause-box">{safe_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_bullet_lines(title: str, lines: List[str], empty_message: str) -> None:
    cleaned = [line.strip() for line in lines if str(line).strip()]

    if not cleaned:
        st.markdown(
            f"""
            <div class="section-card">
                <div class="section-title">{_escape(title)}</div>
                <div class="body-text">{_escape(empty_message)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    bullets_html = "".join(f"<li>{_escape(line)}</li>" for line in cleaned)
    st.markdown(
        f"""
        <div class="section-card">
            <div class="section-title">{_escape(title)}</div>
            <ul class="bullet-list">
                {bullets_html}
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _extract_lines(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    text = str(value or "").strip()
    return [line.strip() for line in text.splitlines() if line.strip()]


def render_evidence_block(evidence: Any) -> None:
    lines = _extract_lines(evidence)
    if not lines:
        return

    render_bullet_lines(
        title="Evidence",
        lines=lines,
        empty_message="",
    )


def render_recommendations_block(recommendations: Any) -> None:
    lines = _extract_lines(recommendations)
    render_bullet_lines(
        title="Recommended next steps",
        lines=lines,
        empty_message="No recommendations available.",
    )


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
        evidence,
        recommendations,
    )


def render_structured_result(result: Dict[str, Any]) -> None:
    status = result.get("status", "Unknown")
    health_score = result.get("health_score", "N/A")
    confidence = result.get("confidence", "N/A")
    summary = result.get("summary", "")
    root_cause = result.get("root_cause", "")
    evidence = result.get("evidence", "")
    recommendations = result.get("recommendations", [])

    evidence_lines = _extract_lines(evidence)

    st.markdown("### Investigation summary")
    top1, top2, top3 = st.columns(3)
    top1.metric("Status", str(status))
    top2.metric("Health score", str(health_score))
    top3.metric("Confidence", str(confidence))

    render_key_value_grid(result)

    if result.get("intent") == "Help" or result.get("resource_type") == "Help":
        st.text(summary or "No details available.")
    else:
        render_text_block("Summary", summary, use_summary_style=True)

    if root_cause:
        render_root_cause(root_cause)

    if evidence_lines:
        col1, col2 = st.columns(2)
        with col1:
            render_evidence_block(evidence_lines)
        with col2:
            render_recommendations_block(recommendations)
    else:
        render_recommendations_block(recommendations)

    if result.get("items") and isinstance(result.get("items"), list):
        st.markdown("### Results")
        st.dataframe(result["items"], use_container_width=True)

    with st.expander("Raw JSON"):
        st.json(result)


def render_text_result(output_text: str) -> None:
    if not output_text.strip():
        st.warning("No output returned.")
        return

    preamble, evidence_lines, recommendation_lines = split_sections(output_text)

    render_text_block("Result", preamble, use_summary_style=True)

    if evidence_lines:
        col1, col2 = st.columns(2)
        with col1:
            render_evidence_block(evidence_lines)
        with col2:
            render_recommendations_block(recommendation_lines)
    else:
        render_recommendations_block(recommendation_lines)

    with st.expander("Raw output"):
        st.text(output_text)


def render_result(result: Any) -> None:
    if isinstance(result, dict):
        expected_keys = {
            "question",
            "intent",
            "resource",
            "resource_type",
            "status",
            "health_score",
            "summary",
        }
        if expected_keys.intersection(set(result.keys())):
            render_structured_result(result)
            return

        if "response" in result:
            render_text_result(str(result["response"]))
            return

        with st.expander("Raw output"):
            st.json(result)
        return

    render_text_result(str(result))


def main() -> None:
    render_page_setup()
    render_custom_css()
    render_header()
    render_sidebar()

    st.markdown(
        """
        <div class="hero-card">
            Ask a Kubernetes troubleshooting question in natural language.
            KubeSage can help with cluster health, namespace health, workload investigation,
            unhealthy resource listing, and deep root cause analysis.
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
            "- analyze my cluster\n"
            "- deep analyze my cluster\n"
            "- investigate missing-secret\n"
            "- deep analyze dns-fail-loop\n"
            "- deep analyze ai-investigator-lab namespace\n"
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
        render_result(result)


if __name__ == "__main__":
    main()