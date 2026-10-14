# Screen Tutor compatibility and ownership map

## Baseline

Current remote \`main\`, the plan baseline, and this build's starting head are all \`53bbb2793eb277faafb4637ae986aca24f2a7b75\`. The isolated worktree began clean. Existing dirty worktrees are unrelated and remain untouched. No open pull request or overlapping test/mutation campaign was active at preflight.

The platform is Python standard-library only. Tutor code must remain disabled by default and must not make the existing headless platform depend on a native client. New tests must be registered in both \`tests/run_all.py\` and \`evidence.py\`. Security powers continue through existing authority modules.

## Actual callable path and owners

| Boundary | Current callable | Current owner | Tutor integration rule |
|---|---|---|---|
| Context assembly | \`context.compile\`, \`context.fit_request\` | \`context.py\` | Observation references enter as bounded, fenced metadata; raw capture does not enter unrelated tasks. |
| Request budget | \`context.assert_request_budget\` | \`context.py\` | Every multimodal request must account for image bytes/tokens before dispatch. |
| Model selection and call | \`loop.Agent.call_model\` | \`loop.py\` | Use the existing routing, key check, request budget, retry, cancellation, and spend path; no second provider client. |
| Usage attribution | \`loop.Agent._meter\`, \`modelgateway.record\`, \`modelgateway.charge\` | \`loop.py\`, \`modelgateway.py\` | Tutor purpose, task, provider, model, latency, tokens, and cost remain attributable. |
| Standing authority | \`grants.check\`, \`grants.record_use\` | \`grants.py\` | Tutor modes consume owner-issued grants; model output cannot create or broaden them. |
| Process execution | \`execution.run\` | \`execution.py\` | Any executable effect keeps role, task, approval, containment, trace, and postcondition enforcement. |
| Mission contract | \`mission.create\`, \`mission.justify\`, \`mission.meet\`, \`mission.close\` | \`mission.py\` | A learning goal or guided task stays bound to explicit criteria and independent evidence. |
| Task execution | \`loop.Agent.add_task\`, drain loop | \`loop.py\` | Explain/Guide can enqueue bounded work; a queued mission is not represented as a running task. |
| Computer observation/action | \`computersession.ComputerSession\`, \`computeruse.BrowserAuthority\` | \`computersession.py\`, \`computeruse.py\` | Reuse task-owned epochs, origin policy, atomic action authorization, effect lineage, cancellation, and postconditions. |
| Procedural mastery | \`mastery._execute_task\` → \`goal.pursue\` → \`contract.verify\` | \`mastery.py\`, \`goal.py\`, \`contract.py\` | This proves agent task execution only; human submissions require a separate evaluator. |
| Product surface | \`ui.py\`, \`ui.html\` | existing panel | Add tutor surfaces behind feature and permission gates; existing flows remain usable with tutor off. |

## Reconciliation of retained computer-use work

Remote main already contains task-owned \`ComputerSession\`, \`BrowserAuthority\`, atomic Playwright observation/action support, cancellation checks, durable action lineage, and independent postcondition verification. These capabilities are accepted only as current source plus their existing local/CI tests. They are reusable foundations, not proof of arbitrary desktop control, native screen capture, tutor quality, or release readiness.

## Protected boundaries

The exact pre-edit hashes are in `BASELINE_LOCK.json`. Any intentional edit to a protected file must identify its packet, update affected tests, explain the compatibility consequence, and create a new reviewed lock revision. `BASELINE_LOCK_SC_1B.json` is the current reviewed revision and preserves the original lock as its immutable predecessor. An unexplained mismatch fails the baseline witness.

## Current blockers outside SC-0A

Provider keys, an approved spend route, native SDK/tooling, real applications and display profiles, human study operations, and release/signing identity are not present. Local contract and feature-off work proceeds without treating these future gates as passed.
