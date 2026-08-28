# MARB Nightwatch: governed autonomous benchmark strategy and implementation prompt

Status: **DESIGN ONLY — no benchmark, provider, model, Docker, deployment, or
spend authorization**

Date: 2026-08-28

Owner: Sunnyday Technologies

## Purpose

Build a bounded overnight research loop for CADCLAW/MARB that can:

- discover and use already-available local models;
- repeat the same frozen benchmark to measure reproducibility, failure rate,
  and the possibility of an unusually successful run;
- compare exact local model revisions without treating a mutable alias as a
  version;
- retain different valid CadQuery solution approaches as evidence instead of
  discarding everything except the best score; and
- prepare a morning report without automatically publishing or changing the
  canonical board.

The design is inspired by Andrej Karpathy's
[`autoresearch`](https://github.com/karpathy/autoresearch) pattern: a small
agent instruction file, fixed evaluation, short bounded experiments, and an
experiment-memory log. It is not a fork and should not copy the upstream
"loop forever" or keep/discard behavior. Benchmark evidence must be finite,
complete, and non-cherry-picked.

## Product boundary

The combined system is the universal evaluation harness:

- **MARB Nightwatch** owns model discovery, model loading, protocol adapters,
  campaign authorization, scheduling, attempt retention, statistics, and the
  separation between exploratory and publishable results.
- **CADCLAW** owns deterministic assembly/inspection/validation interfaces for
  authored STEP parts and exported assemblies. It may expose safer and more
  machine-readable tools, but it does not become a general complex-part
  authoring system.
- **CadQuery** remains the model-controlled authoring surface inside the
  isolated runtime. Model-authored Python must never run in the trusted host
  process.
- **Trusted graders** own answer keys, grading, registration, board changes,
  and publication.

## Why repeats matter

A single successful local-model attempt can be informative, but it cannot
establish typical performance. Nightwatch must retain and report every attempt,
including crashes, invalid exports, and hard-gate failures.

For each exact model fingerprint and frozen benchmark cell, report at minimum:

- attempted, completed, gradeable, and hard-gate-passing counts;
- loadable-STEP rate;
- the full per-attempt scores plus median and range;
- independent-run ordinal or provider seed policy;
- distinct valid solution classes and their frequency;
- exact model, weights/manifest digest when available, quantization, runtime,
  prompt, task, kit, grader, CADCLAW, MARB, image, and host identities; and
- tokens and timing even when monetary cost is zero.

`N >= 3` is the minimum publishable frontier-cell policy. `N >= 9` is the
preferred follow-up for a surprising result, a noisy model, or an upgrade
claim. A single "lucky" run remains visible but is never substituted for the
cohort distribution.

### Replication and cancellation policy

Poor performance is not, by itself, an early-stop condition. Low-capability
models are valuable floor anchors, and mixed failure/success behavior measures
the chance of a rare useful solution.

- Give every authorized, capability-compatible cell its predeclared minimum
  number of attempts before judging productivity.
- Expand a cell from `N >= 3` to `N >= 9` when gradeability is mixed, score
  spread is high, valid solution classes differ, or an incremental model
  revision may have changed behavior.
- Permit a predeclared `N >= 30` low-cost local lane when the question is the
  rate of a rare gradeable or hard-gate-passing outcome. Report a binomial
  interval for success/failure rates; do not infer a continuous score
  distribution from ungradeable attempts.
- Label adaptive expansions and preserve the rule that triggered them. Never
  add attempts only until a desired score appears.
- Operator cancellation, hard campaign limits, resource pressure, repeated
  infrastructure failure, and safety/integrity gates may stop a campaign.
  Cancellation retains every completed and partial attempt and the reason.

## Creative-solution evidence

Novelty is descriptive evidence, not an automatic quality score. A solution
must first pass the applicable correctness and safety gates.

Current `L1-ASSEMBLE` is a closed-reference reconstruction task. A geometrically
different result is not a creative success merely because it looks plausible;
the current benchmark does not yet contain a complete acceptable-solution
resolver for alternative interface topologies.

Keep three task classes separate:

1. `closed-reference-assembly`: current L1-style reconstruction accuracy;
2. `constraint-equivalence-assembly`: multiple accepted topologies resolved by
   frozen functional/interface/manufacturing invariants; and
3. `open-design-exploration`: declared constraints plus human review, with no
   automatic claim that novelty is correctness.

Nightwatch should assign a deterministic `solution_class_id` from disclosed
features such as:

- final STEP geometry/transform fingerprint;
- component and solid counts;
- assembly hierarchy and connector/datum usage where available;
- normalized CadQuery/Python AST feature summary and API-call histogram; and
- source archive digest.

Retain the source archive and STEP for every attempt. Never execute a retained
source archive during clustering. Report the number and frequency of valid
solution classes, with representative run IDs, without claiming that a novel
class is better unless the frozen grader supports that conclusion.

## Local model discovery and loader

Implement the loader in MARB or a separate MARB adapter package, not in the
CADCLAW geometry core.

The initial loader may support already-running or already-installed
OpenAI-compatible local runtimes such as Ollama, LM Studio, vLLM, llama.cpp, or
LocalAI through explicit adapters. It must:

1. perform metadata-only discovery before authorization;
2. never download a model automatically;
3. never execute an unapproved model ID or mutable alias;
4. resolve an exact fingerprint: runtime name/version, model ID, local
   manifest or weights digest when available, quantization, context size,
   prompt template, and tool-protocol capability;
5. load at most one authorized model at a time by default and unload only a
   model it loaded;
6. distinguish `available`, `installed_not_loaded`, `loaded`, `incompatible`,
   `identity_unresolved`, and `unavailable`;
7. run a no-benchmark capability preflight before reserving a benchmark slot;
8. expose health, load, unload, and inference timeouts plus a kill switch;
9. record GPU/runtime provenance without assuming that the endpoint-reported
   model alias identifies exact weights; and
10. keep credentials out of plans, logs, prompts, and retained artifacts.

Current host note (read-only probe, 2026-08-28): no compatible local LLM
service was visible on the standard Ollama, LM Studio, vLLM, or llama.cpp
process/port locations, and no obvious CAD-capable chat weights were found in
the standard local model cache. An unusually configured or remote local server
was not probed. Nightwatch therefore needs the loader/discovery layer, but the
first real campaign also requires an already-installed model runtime and exact
model fingerprint.

### Tool-protocol lanes

Local models vary substantially in tool-call support. Do not silently rewrite
the tool surface to make one model appear compatible.

Support separately versioned lanes:

- `openai-native-tools-v1`: provider returns native structured tool calls;
- `marb-json-tools-v1`: a frozen, schema-validated text/JSON compatibility
  protocol for models without native tool calls; and
- `single-completion-source-v1`: one bounded response containing validated
  source through a frozen broker, followed by sandboxed execution; and
- `text-only-incompatible`: discovery succeeds, but the model is not eligible
  for the current CadQuery agent task.

Results from different tool-protocol lanes remain separate unless the public
method explicitly allows a comparison. Vision is also a separate attested lane
with exact input-image digests; H2b is currently text-only.

## CAD driver adapters and candidate matrix

Keep model lifecycle and CAD-tool lifecycle as independent adapter axes:

- `ModelAdapter`: discovers, fingerprints, loads, calls, and releases one exact
  local model/runtime identity.
- `CADDriverAdapter`: exposes one frozen authoring/tool surface, executes it in
  its qualified isolation boundary, and exports a neutral artifact for trusted
  grading.

CadQuery is the first supported driver because it can run as isolated Python.
Other CAD systems may be added through separate versioned adapters only after
their automation interface, license, isolation, export behavior, and tool
surface are verified. Native-application, GUI, cloud, vision, or proprietary
API drivers are separate benchmark lanes; they must not be pooled with
CadQuery results as though the assistance available were identical.

One benchmark cell is the exact product of:

`model fingerprint × CAD driver/version × tool-protocol lane × modality × task
revision × prompt variant × kit revision × runtime contract`.

Because that matrix can grow quickly, Nightwatch should use staged admission:

1. metadata discovery;
2. capability and license/isolation preflight;
3. the fixed minimum replication cohort;
4. variability/rare-success expansion; and
5. a human-reviewed promotion or retirement proposal.

Retirement prevents future scheduling but never deletes prior evidence.

## External model boundary

Grok, GPT, Claude, and every other metered or externally hosted model are
manual-only. Nightwatch must not discover, load, or call them autonomously.

Each external campaign requires a fresh, separately reviewed authorization
that binds:

- exact provider endpoint and model ID/version;
- data-sharing choice;
- maximum attempts, turns, input tokens, output tokens, wall time, and dollars;
- frozen pre-call pricing policy and abort behavior; and
- the exact task, prompt, kit, image, grader, and campaign identities.

Current MARB H2b accepts only `local-no-charge` and rejects metered calls.
External support is a later versioned change and separate pull request. An API
key's presence is never authorization.

## Campaign contract

Every overnight run begins from a canonical, hash-bound campaign document with
at least:

```yaml
schema: marb_nightwatch_campaign.v1
campaign_id: <new UUID-backed identifier>
mode: exploratory-local | publishable-local
task_id: L1-ASSEMBLE
task_revision: <immutable revision>
prompt_variant: frozen-core
marb_commit: <40-hex>
cadclaw_commit: <40-hex>
kit_sha256: <64-hex>
grader_revision: <immutable revision or null for exploratory-ungraded>
executor_image: <repository>@sha256:<64-hex>
tool_protocol_lane: openai-native-tools-v1
models:
  - model_id: <exact endpoint identity>
    model_fingerprint: <manifest/weights/runtime identity>
    endpoint: <sanitized loopback endpoint>
    billing_mode: local-no-charge
cad_drivers:
  - driver_id: cadquery
    driver_version: <exact version>
    adapter_revision: <immutable revision>
run_policy:
  minimum_attempts_per_cell: 3
  maximum_attempts_per_cell: 9
  maximum_total_attempts: <finite integer>
  maximum_campaign_seconds: <finite integer>
  concurrency: 1
  scheduling: round-robin
  stop_after_consecutive_infrastructure_failures: <finite integer>
publication:
  automatic: false
  board_mutation: false
  site_deployment: false
```

The reviewed campaign digest is the aggregate authorization boundary. Each
attempt still receives its own H2b slot authorization. Campaign-wide locking
must prevent duplicate slot allocation across checkouts and hosts.

## Autonomous loop

Nightwatch runs a finite state machine, not an unbounded agent loop:

1. Verify campaign digest, expiry, hard limits, repository commits, clean
   execution checkout, answer-key readiness, image RepoDigest, executable
   digests, and global campaign lock.
2. Discover only the campaign's named local runtimes and resolve exact model
   fingerprints.
3. Run the no-provider/no-network executor smoke if the host/image pair has not
   already been qualified by the frozen method.
4. Run one baseline canary and stop if harness or grader drift is detected.
5. Select the next unclaimed slot in round-robin order so temperature, time,
   and host drift are not confounded with one model.
6. Execute one slot, retain all partial evidence, run trusted grading when the
   immutable key is available, and append one content-hashed ledger event.
7. Update descriptive statistics and solution-class evidence from all attempts.
8. Continue only while every campaign limit and health gate remains satisfied.
9. Stop cleanly at the finite time/attempt cap or immediately on kill switch,
   identity drift, authorization expiry, repeated infrastructure failure,
   evidence-integrity failure, grader drift, or unexpected cost.
10. Produce a morning summary and review queue. Do not commit scores, mutate
    the board, deploy the site, or contact external parties.

## New benchmarks and datasets

The overnight agent may propose a dataset/task candidate, but it may not invent
or admit one into a campaign. A new benchmark requires a separate intake pull
request with:

- authored STEP components/assembly appropriate to the task;
- redistributable license and provenance;
- public blind-kit definition;
- private or gated answer-key revision;
- deterministic grader and negative controls;
- leak review and prompt fairness review; and
- a calibration cohort before public comparisons.

This applies to a Berkeley robot hand/forearm dataset or any new NIST-derived
component. NIST AP242 fixtures currently qualify CADCLAW's STEP/PMI behavior;
they are not automatically MARB model tasks.

## CADCLAW interface improvements to assess

Do not add a model loader to CADCLAW until the separation above is proven
insufficient. First assess and, where gaps are confirmed, propose versioned
interfaces for:

- a central gate registry shared by CLI, MCP, and library entry points;
- one machine-readable capability manifest for CLI/MCP tool names, versions,
  input/output schemas, and side effects;
- stable JSON output and error taxonomy for inspect, assemble, and validate;
- deterministic artifact and source/provenance hashes;
- sandbox-safe read-only inspection calls and explicitly separated writing
  assembly calls;
- structured repair suggestions tied to specific findings rather than generic
  confidence claims; and
- solution fingerprints that MARB can consume without executing model-authored
  source.

Any CADCLAW change must preserve the rule: authored parts are placed and
verified; CADCLAW does not generate complex replacement geometry or contextual
hole patterns.

### Confirmed CADCLAW autonomous-harness gap

A read-only reproduction on CADCLAW `2be2599f...` confirmed that both:

```text
cadclaw harness --only does_not_exist --report-format json
cadclaw harness --only interference --report-format json
```

return exit code zero with `overall: pass` and `confidence_budget.checked: []`.
The current harness selector accepts arbitrary names, and the declared
interference gate is not wired into that union runner. An autonomous controller
must never interpret an empty check set as a pass.

The first CADCLAW hardening PR should therefore:

1. introduce a versioned `GateRegistry` used consistently by CLI, MCP, and
   library callers;
2. reject unknown `--only` and `--skip` identities;
3. distinguish `pass`, `fail`, `error`, `not_applicable`, `not_checked`, and
   empty selection;
4. wire every advertised gate or stop advertising it through that entry point;
5. add parity tests proving the selected gate IDs equal the reported `checked`
   set; and
6. make an empty requested check set fail closed.

Follow-on CADCLAW improvements should add JSON output to the currently
print-oriented `inspect` queries, a uniform typed/redacted error envelope,
stateless or content-addressed MCP assembly handles instead of process-global
loaded state, a JSON capability command/tool, general artifact provenance, and
canonical evidence payloads separated from volatile host/timing metadata.

## Preconditions before the first real overnight campaign

- [ ] Bind STEP discovery identity to evidence capture so a host-side
  validation-to-copy substitution fails closed.
- [ ] Calibrate and version MARB against the intended updated CADCLAW commit;
  H2b currently pins CADCLAW 0.10.0 at `60fc271f...`.
- [ ] Implement the aggregate campaign ledger and cross-checkout/cross-host
  lock.
- [ ] Build or approve an immutable OCI RepoDigest and pass the exact Windows
  Docker Desktop no-provider/no-network smoke.
- [ ] Implement and test metadata-only local model discovery and exact model
  fingerprinting.
- [ ] Freeze at least one qualified `CADDriverAdapter`; start with CadQuery and
  keep every additional CAD system in its own declared lane.
- [ ] Freeze an exact local model allowlist, endpoint, run cap, and
  local-no-charge authorization.
- [ ] Make the L1 trusted answer key and grading path available without exposing
  it to the model workspace.
- [ ] Keep L2/L4 unmeasured until their immutable gated keys and trusted
  grading/readback paths exist.

## Pull-request sequence

1. **CADCLAW gate registry:** reject unknown/empty harness selections, wire the
   advertised gates, and prove CLI/MCP/library selection parity.
2. **Evidence binding:** close the STEP discovery-to-copy integrity gap and add
   adversarial tests.
3. **Nightwatch plan/ledger:** campaign schema, global reservations, dry-run
   planner, crash-safe append-only journal, status, and summary; no model calls.
4. **Local model adapters:** metadata discovery, exact fingerprint, capability
   preflight, load/unload ownership, and fake-runtime tests; no downloads.
5. **CADCLAW calibration/interfaces:** version the intended CADCLAW pin and add
   only confirmed machine-interface gaps.
6. **Runtime qualification:** private build provenance and manual host/image
   smoke evidence.
7. **First exploratory L1 campaign:** explicitly approved local model(s),
   finite `N >= 3`, all attempts retained, no publication.
8. **Trusted grading/publication review:** separate PR after human review.

## Copy-ready implementation prompt

> Implement **MARB Nightwatch**, a governed autoresearch-style overnight local
> model benchmark controller. Read both repositories' `AGENTS.md` and
> `AGENTS_GIT_PROTOCOL.md`, fetch before work, and use separate pull requests in
> the sequence defined in
> `planning/MARB_NIGHTWATCH_AUTORESEARCH_PROMPT.md`.
>
> Preserve the user-owned untracked MARB paths `publishing/` and
> `.github/workflows/deploy-cloudflare.yml`; do not inspect, modify, stage, or
> commit them. Do not modify or publish historical benchmark results. Never
> expose secrets or credential values.
>
> Phase 1 is implementation and fake-only validation. It does **not** authorize
> Docker build/run, model loading, provider/model calls, downloads, spend,
> grading-key publication, board mutation, site deployment, or outreach.
>
> Start by reproducing and closing CADCLAW's empty-check false-pass behavior:
> unknown `harness --only/--skip` names must be rejected, every advertised gate
> must be wired consistently, and an empty requested check set must never report
> `overall: pass`. Implement a shared, versioned gate registry and CLI/MCP/library
> parity tests in a dedicated CADCLAW PR.
>
> Next, independently validate and close the STEP
> `_find_step_output()`-to-`_copy_evidence()` identity gap. Then implement a
> canonical `marb_nightwatch_campaign.v1` schema; a content-hashed, crash-safe,
> append-only aggregate ledger; cross-checkout/cross-host slot locking; finite
> attempt/time/concurrency limits; metadata-only local-model discovery; exact
> model/runtime/weights-or-manifest fingerprinting; explicit load/unload
> ownership; a kill switch; and fake runtime/provider tests. No infinite loop
> is allowed.
>
> Keep native tool calling and JSON compatibility tool calling in separately
> versioned benchmark lanes. Add a distinct bounded single-completion-source
> lane for compatible local models that cannot call tools reliably. Never
> silently substitute one lane for another. Never auto-download a model. Never call an unknown
> alias. Preserve every attempt and partial failure. Compute reproducibility,
> gradeability, hard-gate rate, score distribution, and descriptive valid
> solution-class diversity without cherry-picking. A new model revision is a
> new cell. `N >= 3` is the minimum publishable frontier policy; surprising or
> noisy results should be proposed for `N >= 9`, and a predeclared low-cost
> local rare-success study may use `N >= 30`. Poor performance alone is not an
> early-stop rule. Record the trigger for every adaptive expansion and retain
> all cancelled or partial attempts.
>
> Implement separate `ModelAdapter` and `CADDriverAdapter` contracts. CadQuery
> is the first driver. Treat each additional CAD package, automation surface,
> version, modality, and tool protocol as a distinct benchmark lane with its
> own licensing, isolation, export, and fairness evidence.
>
> Treat the current L1 task as closed-reference reconstruction. Add no
> "creative success" claim for a different topology until a separate
> constraint-equivalence task freezes its acceptable-solution resolver. Keep
> open-design exploration in a human-reviewed lane, with novelty orthogonal to
> correctness.
>
> External/metred models including Grok, GPT, and Claude are out of scope.
> Design an approval boundary for a future provider-specific implementation,
> but current code must remain local-no-charge only and must reject metered
> calls.
>
> Inspect CADCLAW's current CLI/MCP/JSON surfaces and produce a repo-grounded gap
> assessment before changing CADCLAW. Put model lifecycle/orchestration in MARB,
> not CADCLAW. Add CADCLAW interfaces only where a demonstrated gap prevents
> deterministic, sandbox-safe assembly/inspection/validation or solution
> fingerprinting. Preserve CADCLAW's authored-STEP placement boundary.
>
> For each PR: keep scope independently reviewable, add adversarial and normal
> controls, run the applicable focused and full policy suites, scan staged
> diffs for secrets, prove the exact commit in a clean checkout, and update the
> durable completion ledger. Stop before the first real local model call and
> present the exact campaign, model fingerprints, image RepoDigest, limits, and
> authorization literal for human approval.

## Completion definition

The strategy is not complete merely because a scheduler runs. Completion
requires a reviewed implementation, qualified runtime, finite approved local
campaign, retained evidence for every attempt, trusted grading, a morning
summary that separates exploratory from publishable results, and explicit
human approval before any board/site/outreach action.
