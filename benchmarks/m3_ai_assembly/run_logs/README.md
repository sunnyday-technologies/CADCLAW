# Benchmark Run Logs

This folder stores non-secret run manifests for the M3 AI assembly benchmark.
Each run log records how many attempts, retries, corrections, human
interventions, elapsed time, and token counts were needed to reach an exported
artifact.

The goal is an artifact-based comparison between workflows, not a preference
claim about any AI lab, model, or CAD vendor.

## What Counts

- **Attempt:** one cycle where the AI driver receives the prompt/current state,
  changes or exports an assembly artifact, and the artifact is checked.
- **Retry:** any attempt after the first for the same target run.
- **Correction:** a concrete change made because a review image, CADCLAW
  finding, human observation, or failed command found a problem.
- **Human intervention:** human-provided design information, approval,
  correction, or native-CAD operation that materially changes the run.

## Token And Time Policy

Record token counts only from provider, API, or host-application telemetry. Do
not estimate tokens from transcript length. If token telemetry is unavailable,
set `token_usage.capture_status: unavailable` and explain the gap.

Record wall-clock time using a consistent start and stop:

- Start: the moment the shared prompt is given to the AI driver.
- Stop: the moment the final graded report and score are written, or the run is
  abandoned with a blocker.

## Files

- `templates/run_log_template.yaml` is the blank template for future runs.
- `initial_cadclaw_setup_2026_05.yaml` is a retrospective best-effort log for
  the first CADCLAW setup pass. It marks unavailable timing/token data as
  unavailable rather than guessing.
