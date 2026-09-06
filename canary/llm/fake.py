"""Offline evidence-driven fixture provider; confidence rules are demo policy only."""

from .base import ModelResponse, ToolCall


LAYOUT_KEYS = ("can_id", "start_bit", "width_bits", "endian", "signed")


def layout(value):
    return {key: value[key] for key in LAYOUT_KEYS}


class FakeProvider:
    def respond(self, system, messages, tools, conclusion_schema):
        events = [m.content for m in messages if m.role == "tool" and m.content["output"]["ok"]]
        if not events:
            return ModelResponse(tool_calls=[ToolCall("summary", "summarize_capture", {}),
                                              ToolCall("search", "search_candidates", {"top_n": 10})])
        search = next(e["output"]["result"] for e in events if e["name"] == "search_candidates")
        hypotheses = search["hypotheses"]
        if not hypotheses:
            return ModelResponse(text="No candidate has defined correlation.")
        analyses = [e["output"]["result"] for e in events if e["name"] == "analyze_candidate"]
        if not analyses:
            # Compare the closest distinct hypothesis and, when visible, the
            # strongest hypothesis on another ID. No field meaning is assumed.
            choices = hypotheses[:2]
            # Affine layouts are ambiguity evidence, not distinct alternatives.
            distinct = hypotheses[0].get('distinct_alternatives', [])
            additional = next((h for h in hypotheses if any(layout(h['representative']) == layout(e['candidate'])
                               for e in distinct)), None)
            if additional and additional not in choices:
                choices = [*choices, additional]
            other = next((h for h in hypotheses[2:] if h["representative"]["can_id"] != choices[0]["representative"]["can_id"]), None)
            if other and other not in choices:
                choices = [*choices, other]
            calls = [ToolCall("inspect", "inspect_can_id", {"can_id": choices[0]["representative"]["can_id"]})]
            calls.extend(ToolCall(f"analysis-{i}", "analyze_candidate", {**layout(h["representative"]), "include_fit": True})
                         for i, h in enumerate(choices))
            return ModelResponse(tool_calls=calls)
        fitted = [a for a in analyses if a.get("fit") is not None]
        if not fitted:
            return ModelResponse(text="No compared candidate has a defined fit.")
        best = min(fitted, key=lambda a: (a["fit"]["rmse"], -a["fit"]["r_squared"]))
        field = layout(best)
        if "byte_offset" in best:
            field["byte_offset"] = best["byte_offset"]
        group = best["equivalence"]
        equivalents = [layout(c) for c in [group["representative"], *group["equivalent_candidates"]]
                       if layout(c) != layout(best)]
        affine = [layout(e['candidate']) for e in best.get('affine_equivalents', [])]
        alternatives = [{"candidate": layout(a), "correlation": a["correlation"],
                         **{k: a["fit"][k] for k in ("rmse", "mae", "r_squared")},
                         "reason": "Compared fitted reconstruction; selected candidate has no greater RMSE on its aligned samples."}
                        for a in fitted if a is not best and layout(a) not in [*equivalents, *affine]]
        r, score = abs(best["correlation"]), best["fit"]["r_squared"]
        # Explicit deterministic fake policy, not calibrated confidence or an
        # additional discovery/ranking algorithm. Live models judge the evidence.
        signal = "high" if r >= 0.995 and score >= 0.99 else "medium" if r >= 0.9 and score >= 0.8 else "low"
        comparable = any(a["rmse"] <= best["fit"]["rmse"] * 1.05 + 1e-12 for a in alternatives)
        layout_confidence = "low" if equivalents or affine else "medium" if signal == "high" and comparable else signal
        ambiguity = (f"{len(equivalents)+1} layouts decode identically; this capture cannot distinguish the exact layout."
                     if equivalents else "No identical alternative exists in the supported search space on this capture.")
        if affine:
            ambiguity += (' Different raw encodings are affine-equivalent on this capture; '
                          'the reference cannot distinguish their reconstructions after scale/offset fitting.')
        rationale = (f"Reference tracking: correlation {best['correlation']:.9g}, R-squared {score:.9g}, "
                     f"RMSE {best['fit']['rmse']:.6g}. {ambiguity} "
                     f"Compared {len(alternatives)} non-equivalent alternatives. Confidence is qualitative, not proof of signal identity.")
        return ModelResponse(conclusion={"reference_name": messages[0].content["reference_name"],
            "selected_candidate": field, "correlation": best["correlation"], **best["fit"],
            "confidence": signal, "signal_confidence": signal, "layout_confidence": layout_confidence,
            "layout_ambiguous": bool(equivalents or affine), "equivalent_layouts": equivalents,
            "affine_equivalent_layouts": affine, 'ambiguity_reason': best['ambiguity_reason'],
            "alternative_candidates": alternatives, "rationale": rationale})
