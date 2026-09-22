"""Guards: the `all-checks-pass` gate must cover what can only reach it.

The ``all-checks-pass`` job is the only check branch protection requires, and
it is also the sole feed for the synthesized PR review comment:
``scripts/ci/assemble_review_comment.py::collect_failed_jobs`` builds its error
items from the ``needs-json`` dict this job emits. A sub-workflow job that is
missing from its ``needs`` list is therefore advisory-only on both paths -- it
can neither block a merge nor explain itself in the comment.

Two invariants keep that from regressing silently:

1. every always-on sub-workflow of ``ci.yaml`` is a gate dependency
   (regression: ``infographic-check`` was silently advisory);
2. every job whose called workflow declares a ``review_status`` output is a
   gate dependency, because that output has no other consumer that this
   repository can see -- a job outside the gate can fail with neither a merge
   block nor a comment line.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yaml"

# Jobs that are not gate dependencies on purpose. Keep this empty or document
# each entry with the reason it cannot be required; an undocumented exemption
# defeats the guard above.
GATE_EXEMPT_REVIEW_STATUS: dict[str, str] = {}


def _ci():
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def _workflow_call_outputs(job: dict) -> set[str]:
    """The ``outputs`` a called workflow declares for ``workflow_call``."""
    uses = job.get("uses")
    if not isinstance(uses, str) or not uses.startswith("./.github/workflows/"):
        return set()
    path = ROOT / uses[len("./"):]
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(workflow, dict):
        return set()
    # PyYAML reads the YAML 1.1 key `on` as the boolean True, so accept both.
    triggers = workflow.get("on", workflow.get(True, {}))
    if not isinstance(triggers, dict):
        return set()
    call = triggers.get("workflow_call") or {}
    return set((call.get("outputs") or {}))


def test_unconditional_sub_workflows_are_gate_dependencies():
    ci = _ci()
    jobs = ci["jobs"]
    gate_needs = set(jobs["all-checks-pass"]["needs"])
    unconditional = [
        name
        for name, job in jobs.items()
        if name not in {"detect", "all-checks-pass", "ci-timings"}
        and "uses" in job  # sub-workflow calls only
        and "if" not in job
    ]
    assert unconditional, "expected at least one unconditional sub-workflow"
    missing = sorted(set(unconditional) - gate_needs)
    assert not missing, (
        "unconditional sub-workflows missing from all-checks-pass needs: %s" % missing
    )


def test_review_status_producers_are_gate_dependencies():
    ci = _ci()
    jobs = ci["jobs"]
    gate_needs = set(jobs["all-checks-pass"]["needs"])
    missing = sorted(
        name
        for name, job in jobs.items()
        if "review_status" in _workflow_call_outputs(job)
        and name not in gate_needs
        and name not in GATE_EXEMPT_REVIEW_STATUS
    )
    assert not missing, (
        "jobs declare a `review_status` output that can only reach the review "
        "comment through all-checks-pass.needs, but are not gate dependencies: "
        "%s. A failure in one of these is neither merge-blocking nor explained "
        "in the PR comment." % missing
    )
