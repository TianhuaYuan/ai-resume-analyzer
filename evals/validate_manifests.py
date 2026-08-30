from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    baselines = json.loads((root / "baselines.json").read_text(encoding="utf-8"))
    tiers = json.loads((root / "model_tiers.json").read_text(encoding="utf-8"))
    faults = json.loads((root / "fault_matrix.json").read_text(encoding="utf-8"))
    capabilities = json.loads((root / "model_capabilities.json").read_text(encoding="utf-8"))
    ids = [x["id"] for x in baselines["baselines"]]
    assert len(ids) == len(set(ids)) and {"prompt_only", "agentic_rag", "single_agent"} <= set(ids)
    assert {"all_strong", "all_cheap", "tiered"} <= set(tiers["tiers"])
    assert len(faults["faults"]) >= 8 and len({x["id"] for x in faults["faults"]}) == len(faults["faults"])
    assert capabilities["capabilities"]["main_chat"]["disabled_baseline"] is False
    print(json.dumps({"valid": True, "baselines": len(ids), "ablations": len(baselines["ablations"]), "tiers": len(tiers["tiers"]), "faults": len(faults["faults"]), "capabilities": len(capabilities["capabilities"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
