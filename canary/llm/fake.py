"""Deterministic offline provider exercising the same tool loop."""

from .base import ModelResponse, ToolCall


class FakeProvider:
    def respond(self, system, messages, tools, conclusion_schema):
        events = [m.content for m in messages if m.role == "tool" and m.content["output"]["ok"]]
        if not events:
            return ModelResponse(tool_calls=[ToolCall("summary", "summarize_capture", {}),
                                              ToolCall("search", "search_candidates", {"top_n": 3})])
        search = next(e["output"]["result"] for e in events if e["name"] == "search_candidates")
        if not search["results"]:
            return ModelResponse(text="No candidate has defined correlation.")
        best = search["results"][0]
        analysis = next((e["output"]["result"] for e in events if e["name"] == "analyze_candidate"), None)
        if analysis is None:
            args = {k: best[k] for k in ("can_id", "start_bit", "width_bits", "endian", "signed")}
            return ModelResponse(tool_calls=[ToolCall("inspect", "inspect_can_id", {"can_id": best["can_id"]}),
                                              ToolCall("analysis", "analyze_candidate", {**args, "include_fit": True})])
        field = {k: analysis[k] for k in ("can_id", "start_bit", "width_bits", "endian", "signed")}
        if "byte_offset" in analysis:
            field["byte_offset"] = analysis["byte_offset"]
        return ModelResponse(conclusion={"reference_name": messages[0].content["reference_name"],
            "selected_candidate": field, "correlation": analysis["correlation"], **analysis["fit"],
            "confidence": "medium", "rationale": "Highest absolute correlation in deterministic search; fitted metrics support tracking the reference. Correlation does not prove semantic identity."})
