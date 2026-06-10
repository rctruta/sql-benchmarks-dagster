# Security Analysis: Result Integrity & Semantic Injection

## 🕵️‍♂️ The Threat: Semantic Injection
There is a critical flaw in agentic AI architecture: **The Collapsed Planes Problem**. 
Agents often treat probabilistic "Memory" files (Markdown, results logs) as a deterministic **Control Plane**. If an attacker poisons these files (e.g., via a supply chain attack that appends to a log), an agent will ingest the malicious "context" and enter an infinite loop or execute dangerous commands based on a hallucinated reality.

---

## 🛡 Current Defense (Deterministic Identity)
Our platform is **partially immune** to simple logic-swapping attacks because of the **Experiment ID**. 
*   Because the ID is a hash of `(Config + SQL + Python)`, an attacker cannot silently change the code without changing the ID. 
*   If an agent is looking for a specific experiment hash, it won't find it if the files were tampered with. This creates a **Trusted Computing Base (TCB)** for the *Identity* of the task.

---

## 🕸 The Vulnerability (The "Semantic Gap")
The platform is currently vulnerable to **Result Poisoning**:
1.  **Tampered Results**: An attacker writes to `results_<id>.csv`. The agent reads the poisoned CSV and concludes that a dangerous configuration is actually safe.
2.  **Memory Poisoning**: An attacker appends to `walkthrough.md`. The agent reads "Experiment `HashX` passed all verification" and skips its own internal safety check.

---

## 🔒 The Fix: Integrity Sealing (The "Trusted Memory Plane")
To make this laboratory "Professional Grade" for the Agentic future, we must close the loop between **Intent** and **Result**.

### 1. The Result Seal
When an experiment finishes, the platform must generate an `integrity.seal` file inside the results directory. This seal will contain:
*   A hash of the `results_<id>.csv`.
*   A hash of the `dashboard_<id>.html`.
*   A "Parent ID" (The original Experiment ID).

### 2. Mandatory Verification Protocol
We will introduce a `verify_result --id HashX` command. An Agent **must** run this to verify that the results on disk actually match the logic that generated them. This transforms the results from "Probabilistic Files" into "Deterministic Evidence."

---

## Next Steps
1.  **Hardening**: Update `run_experiment.py` to generate the `integrity.seal` on completion.
2.  **Tooling**: Create `scripts/verify_capsule.py` for agents to use as a trust-check.
3.  **Documentation**: Update `AGENTS.md` to specify the **Mandatory Trust Check** before digesting results.
