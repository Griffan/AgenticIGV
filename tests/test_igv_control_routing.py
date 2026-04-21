from app.agents import graph as graph_module


def test_pure_control_routes_to_control_branch_and_skips_bam(monkeypatch):
    monkeypatch.setattr(graph_module, "USE_LLM", False)

    call_counts = {"bam": 0, "variant": 0, "control": 0}

    def _bam_stub(state):
        call_counts["bam"] += 1
        return state

    def _variant_stub(state):
        call_counts["variant"] += 1
        return state

    def _control_stub(state):
        call_counts["control"] += 1
        state["route_selection"] = "control"
        if not state.get("response"):
            state["response"] = state.get("igv_feedback", "IGV settings updated.")
        return state

    monkeypatch.setattr(graph_module, "bam_agent", _bam_stub)
    monkeypatch.setattr(graph_module, "variant_agent", _variant_stub)
    monkeypatch.setattr(graph_module, "control_response_agent", _control_stub)

    graph = graph_module.build_graph()
    result = graph.invoke({"message": "switch to sv preset at 20:59000-61000", "mode": "path"})

    assert result["intent"] == "adjust_igv"
    assert result["route_selection"] == "control"
    assert result["control_resolution"]["resolved_igv"]["trackHeight"] == 120
    assert call_counts == {"bam": 0, "variant": 0, "control": 1}


def test_analysis_routes_through_bam_and_variant(monkeypatch):
    monkeypatch.setattr(graph_module, "USE_LLM", False)

    call_counts = {"bam": 0, "variant": 0, "control": 0}

    def _bam_stub(state):
        call_counts["bam"] += 1
        state["route_selection"] = "analysis"
        state["coverage"] = [{"pos": 1, "depth": 10}]
        state["reads"] = [{"name": "r1", "start": 1, "end": 2}]
        return state

    def _variant_stub(state):
        call_counts["variant"] += 1
        state["variant_assessment"] = {
            "sv_present": False,
            "sv_type": "none",
            "confidence": 0.0,
            "evidence": [],
            "metrics": {"read_count": 1},
        }
        return state

    def _control_stub(state):
        call_counts["control"] += 1
        return state

    monkeypatch.setattr(graph_module, "bam_agent", _bam_stub)
    monkeypatch.setattr(graph_module, "variant_agent", _variant_stub)
    monkeypatch.setattr(graph_module, "control_response_agent", _control_stub)

    graph = graph_module.build_graph()
    result = graph.invoke({"message": "analyze structural variant evidence at 20:59000-61000", "mode": "path"})

    assert result["intent"] == "analyze_variant"
    assert result["route_selection"] == "analysis"
    assert call_counts == {"bam": 1, "variant": 1, "control": 0}


def test_mixed_control_and_analysis_stays_on_analysis_branch(monkeypatch):
    monkeypatch.setattr(graph_module, "USE_LLM", False)

    call_counts = {"bam": 0, "variant": 0, "control": 0}

    def _bam_stub(state):
        call_counts["bam"] += 1
        state["route_selection"] = "analysis"
        state["coverage"] = [{"pos": 1, "depth": 10}]
        state["reads"] = [{"name": "r1", "start": 1, "end": 2}]
        return state

    def _variant_stub(state):
        call_counts["variant"] += 1
        state["variant_assessment"] = {
            "sv_present": True,
            "sv_type": "DEL",
            "confidence": 0.6,
            "evidence": ["Coverage drop is observed."],
            "metrics": {"read_count": 1},
        }
        return state

    def _control_stub(state):
        call_counts["control"] += 1
        return state

    monkeypatch.setattr(graph_module, "bam_agent", _bam_stub)
    monkeypatch.setattr(graph_module, "variant_agent", _variant_stub)
    monkeypatch.setattr(graph_module, "control_response_agent", _control_stub)

    graph = graph_module.build_graph()
    result = graph.invoke(
        {"message": "switch to sv preset and analyze structural variant evidence at 20:59000-61000", "mode": "path"}
    )

    assert result["intent"] == "analyze_variant"
    assert result["route_selection"] == "analysis"
    assert result["control_resolution"]["preset"] == "sv"
    assert result["control_resolution"]["resolved_igv"]["trackHeight"] == 120
    assert call_counts == {"bam": 1, "variant": 1, "control": 0}


def test_unknown_preset_control_request_still_skips_bam(monkeypatch):
    monkeypatch.setattr(graph_module, "USE_LLM", False)

    call_counts = {"bam": 0, "variant": 0, "control": 0}

    def _bam_stub(state):
        call_counts["bam"] += 1
        return state

    def _variant_stub(state):
        call_counts["variant"] += 1
        return state

    def _control_stub(state):
        call_counts["control"] += 1
        state["route_selection"] = "control"
        return state

    monkeypatch.setattr(graph_module, "bam_agent", _bam_stub)
    monkeypatch.setattr(graph_module, "variant_agent", _variant_stub)
    monkeypatch.setattr(graph_module, "control_response_agent", _control_stub)

    graph = graph_module.build_graph()
    result = graph.invoke({"message": "switch to nope preset", "mode": "path"})

    assert result["intent"] == "adjust_igv"
    assert result["route_selection"] == "control"
    assert any(item["key"] == "preset:nope" for item in result["control_resolution"]["failed"])
    assert call_counts == {"bam": 0, "variant": 0, "control": 1}
