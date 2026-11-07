"""The contract types hold a record shape with no job-search vocabulary (docs/tracker-contract.md)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tracker_state.contract import (
    ActionResult, ActionSpec, ColumnSpec, FieldSpec, KindGuardedStore, RecordRef, RecordSpec, RecordView,
    SectionSpec, TrackerSpec, UnknownKind,
)
from tracker_state.user_state_transition import Dismiss, apply_action


def test_record_ref_identity_is_opaque_and_hashable():
    a, b = RecordRef("event", "1"), RecordRef("event", "1")
    assert a == b and len({a, b}) == 1


def test_record_view_renders_without_the_tracker_computing_anything():
    view = RecordView(
        ref=RecordRef("event", "1"),
        title="Jazz night",
        fields={"venue": ("text", "Pustervik"), "featured": ("badge", "featured", "accent")},
        section="2026-11-03",
        sort_key=("2026-11-03", "20:00"),
        state=None,
        actions=["dismiss"],
        detail={"description": ("text", "Quartet")},
    )
    assert view.fields["venue"] == ("text", "Pustervik")
    assert "dismiss" in view.actions


def test_spec_is_static_and_declares_its_own_vocabulary():
    spec = RecordSpec(
        kind="event", label_singular="event", label_plural="events",
        fields=(FieldSpec("venue", "Venue", "text"),),
        columns=(ColumnSpec("title", ("venue",)),),
        sections=(SectionSpec("upcoming", "Upcoming"),),
        actions=(ActionSpec("dismiss", "Dismiss", kind="secondary"),),
    )
    assert spec.kind == "event" and spec.fields[0].id == "venue"


def test_tracker_spec_may_mix_several_kinds_by_default():
    event = RecordSpec(kind="event", label_singular="event", label_plural="events")
    submission = RecordSpec(kind="submission", label_singular="submission", label_plural="submissions")
    spec = TrackerSpec(specs=(event, submission))
    assert spec.kinds == {"event", "submission"}


def test_tracker_spec_rejects_zero_specs():
    with pytest.raises(ValueError, match="at least one"):
        TrackerSpec(specs=())


def test_one_spec_instance_serves_only_that_kind_and_refuses_a_foreign_one():
    job = RecordSpec(kind="job", label_singular="job", label_plural="jobs")
    one = TrackerSpec(specs=(job,))
    assert one.kinds == {"job"} and one.accepts(RecordRef("job", "1"))
    assert not one.accepts(RecordRef("event", "1"))
    with pytest.raises(UnknownKind):
        one.spec_for("event")


def test_a_section_column_or_action_naming_a_kind_with_no_spec_fails_at_construction():
    def board(**part):
        return TrackerSpec(specs=(RecordSpec(kind="job", label_singular="j", label_plural="js", **part),))
    with pytest.raises(UnknownKind, match="event"):
        board(sections=(SectionSpec("s", "S", kinds=("event",)),))
    with pytest.raises(UnknownKind, match="event"):
        board(columns=(ColumnSpec("title", kinds=("event",)),))
    with pytest.raises(UnknownKind, match="event"):
        board(actions=(ActionSpec("a", "A", kinds=("event",)),))
    board(sections=(SectionSpec("s", "S", kinds=("job",)),))  # a kind with a spec is fine


def test_a_view_of_an_unserved_kind_or_unknown_section_is_refused():
    job = RecordSpec(kind="job", label_singular="j", label_plural="js", sections=(SectionSpec("must", "Must"),))
    spec = TrackerSpec(specs=(job,))
    ok = RecordView(RecordRef("job", "1"), "t", {}, "must", (), None, [])
    assert spec.check_view(ok) is ok
    with pytest.raises(UnknownKind):
        spec.check_view(RecordView(RecordRef("event", "1"), "t", {}, "must", (), None, []))
    with pytest.raises(ValueError, match="section"):
        spec.check_view(RecordView(RecordRef("job", "1"), "t", {}, "nowhere", (), None, []))


class _RecordingStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, RecordRef]] = []

    def snapshot(self):
        calls = self.calls

        class Lookup:
            def is_completed(self, ref): calls.append(("completed", ref)); return False
            def is_dismissed(self, ref): calls.append(("dismissed", ref)); return False
            def ever_completed(self, ref): calls.append(("ever", ref)); return False
        return Lookup()

    def apply(self, action, ref, *, actor):
        self.calls.append(("apply", ref))
        return apply_action(None, action, now="2026-11-01T00:00:00+00:00")

    def history(self, ref):
        self.calls.append(("history", ref))
        return []


def test_the_store_boundary_refuses_a_ref_whose_kind_has_no_spec():
    spec = TrackerSpec(specs=(RecordSpec(kind="job", label_singular="j", label_plural="js"),))
    inner = _RecordingStore()
    store = KindGuardedStore(inner, spec)
    bad = RecordRef("event", "7")
    with pytest.raises(UnknownKind):
        store.apply(Dismiss(), bad, actor="t")
    with pytest.raises(UnknownKind):
        store.history(bad)
    with pytest.raises(UnknownKind):
        store.snapshot().is_dismissed(bad)
    assert inner.calls == []  # nothing reached the backend
    good = RecordRef("job", "1")
    assert store.apply(Dismiss(), good, actor="t").changed
    assert store.history(good) == [] and store.snapshot().is_completed(good) is False


def test_no_any_in_the_contract_module():
    tree = ast.parse(Path(__file__).parent.parent.joinpath("src/tracker_state/contract.py").read_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "Any" not in names


def test_tracker_spec_rejects_duplicate_kinds():
    with pytest.raises(ValueError, match="duplicate"):
        TrackerSpec(specs=(RecordSpec(kind="job", label_singular="j", label_plural="js"),
                            RecordSpec(kind="job", label_singular="j2", label_plural="j2s")))


def test_section_spec_kinds_defaults_to_any():
    assert SectionSpec("upcoming", "Upcoming").kinds == ()
    assert SectionSpec("pending", "Pending", kinds=("submission",)).kinds == ("submission",)


def test_action_result_outcome_is_never_a_bare_truthy_falsy():
    refused = ActionResult(outcome="refused", reason="application_on_record")
    changed = ActionResult(outcome="changed")
    assert refused.outcome != changed.outcome
    assert refused.view is None


def test_module_imports_nothing_job_specific():
    tree = ast.parse(Path(__file__).parent.parent.joinpath("src/tracker_state/contract.py").read_text())
    roots = {
        (n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
        for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in getattr(n, "names", [None])
    }
    assert not roots & {"jobsearch", "composition", "job_repository", "tracker", "cover_letter", "libraries"}
