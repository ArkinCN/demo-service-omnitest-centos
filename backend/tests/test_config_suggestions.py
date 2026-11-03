import json
from copy import deepcopy

import pytest
from app.services.config_suggestions import SuggestionRequest, model_prompt, parse_proposal, validate_context


def request(stage="init"):
    return SuggestionRequest.model_validate({
        "stage": stage, "scene_id": "fixture", "model": "authorized-model",
        "fields": [{"id": stage + ".cp.start.current", "name": "Start current", "kind": "number",
                    "current": 1.0, "minimum": 0.0, "maximum": 2.0, "step": 0.1}],
        "evidence": [{"id": "source-1", "title": "Fixture evidence", "text": "Fixture only"}],
    })


def proposal():
    return {"summary": "Review current", "changes": [{"field_id": "init.cp.start.current",
            "before": 1.0, "after": 1.2, "reason": "Supported by fixture", "evidence_ids": ["source-1"]}], "questions": []}


def test_supported_numeric_change_and_fenced_json():
    raw = json.dumps(proposal())
    assert parse_proposal(raw, request()).changes[0].after == 1.2
    assert parse_proposal("```json\n" + raw + "\n```", request()).changes[0].after == 1.2


def test_selection_prompt_uses_boolean_example_without_weakening_validation():
    body = request("req")
    body.fields[0].id = "req.TR-START-01"
    body.fields[0].kind = "selection"
    body.fields[0].current = False
    prompt = model_prompt(body)
    assert '"before":false,"after":true' in prompt
    assert '"before":0,"after":1' not in prompt
    change = proposal()
    change["changes"][0].update(field_id="req.TR-START-01", before=False, after=True)
    assert parse_proposal(json.dumps(change), body).changes[0].after is True
    change["changes"][0].update(before=0, after=1)
    with pytest.raises(ValueError):
        parse_proposal(json.dumps(change), body)


@pytest.mark.parametrize("patch", [
    {"after": True}, {"after": "1.2"}, {"after": 2.1}, {"after": -0.1},
    {"after": 1.25}, {"after": None}, {"after": float("nan")}, {"after": float("inf")},
    {"before": 0.9}, {"after": 1.0}, {"field_id": "run.cp.other"},
    {"evidence_ids": ["invented"]}, {"evidence_ids": []}, {"execute": True},
])
def test_reject_invalid_change(patch):
    value = proposal()
    value["changes"][0].update(patch)
    with pytest.raises(ValueError):
        parse_proposal(json.dumps(value), request())


def test_reject_duplicate_changes_and_duplicate_json_properties():
    value = proposal()
    value["changes"].append(deepcopy(value["changes"][0]))
    with pytest.raises(ValueError):
        parse_proposal(json.dumps(value), request())
    with pytest.raises(ValueError):
        parse_proposal('{"summary":"one","summary":"two","changes":[],"questions":[]}', request())


def test_allow_no_recommendation_but_reject_refusal_and_incomplete_json():
    assert parse_proposal('{"summary":"Insufficient evidence","changes":[],"questions":["Check source"]}', request()).changes == []
    for raw in ["I cannot help", '{"summary":', "[]", "{}"]:
        with pytest.raises(ValueError):
            parse_proposal(raw, request())


def test_requirement_scope_cannot_change_thresholds():
    body = request()
    body.stage = "req"
    with pytest.raises(ValueError):
        validate_context(body)
    body.fields[0].id = "req.TR-1"
    body.fields[0].kind = "selection"
    body.fields[0].current = True
    value = proposal()
    value["changes"][0].update(field_id="req.TR-1", before=True, after=False)
    assert parse_proposal(json.dumps(value), body).changes[0].after is False
    value["changes"][0]["after"] = 0
    with pytest.raises(ValueError):
        parse_proposal(json.dumps(value), body)


def test_enum_exact_type_and_unknown_extra_properties():
    body = request()
    body.fields[0].kind = "enum"
    body.fields[0].options = [0, 1]
    value = proposal()
    value["changes"][0]["after"] = 0
    assert parse_proposal(json.dumps(value), body).changes[0].after == 0
    value["changes"][0]["after"] = False
    with pytest.raises(ValueError):
        parse_proposal(json.dumps(value), body)
    value = proposal()
    value["start_device"] = True
    with pytest.raises(ValueError):
        parse_proposal(json.dumps(value), request())


def test_duplicate_context_and_untrusted_prompt_boundary():
    body = request()
    body.fields.append(body.fields[0])
    with pytest.raises(ValueError):
        validate_context(body)
    prompt = model_prompt(request())
    assert "untrusted DATA" in prompt and "No tools" in prompt


def test_reject_fraction_hidden_by_integer_editor():
    body = request()
    body.fields[0].step = None
    body.fields[0].precision = 0
    value = proposal()
    value["changes"][0]["after"] = 1.5
    with pytest.raises(ValueError):
        parse_proposal(json.dumps(value), body)
