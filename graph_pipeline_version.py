"""Lightweight deployment identity shared by OCR and public health checks."""

EVIDENCE_PIPELINE_VERSION = '2026-10-26-evidence-two-pass-v3'
AGENT_PIPELINE_VERSION = '2026-10-27-fast-editable-v5'


def graph_nextgen_enabled():
    """Default to the current architecture; retain the explicit 0/1 gate."""
    import os
    return os.environ.get('DMATE_GRAPH_NEXTGEN', '1') == '1'


def active_pipeline():
    """Existing nextgen gate selects this engine; no new variable is required."""
    import os
    value = os.environ.get('DMATE_GRAPH_PIPELINE', 'agent-tools').strip()
    return value if value in ('agent-tools', 'evidence-two-pass') else 'agent-tools'


def active_pipeline_version():
    return AGENT_PIPELINE_VERSION if active_pipeline() == 'agent-tools' else EVIDENCE_PIPELINE_VERSION
