# GX10 MARB benchmark handoff — 2026-08-31

Status: execution plan and verified inventory; not a completed qualification or
benchmark result.

## Execution decision

- The two GX10 systems are the execution hosts for local-model CADCLAW/MARB
  benchmarks.
- Windows may orchestrate the run and retain evidence, but it is not the target
  runtime for local-model inference or the isolated CAD workload.
- Model inference and the isolated CAD executor remain separate processes. Do
  not mount a Docker socket into a model or agent container.
- Do not use x86_64 emulation to represent a Blackwell-native qualification.

## Live inventory snapshot

Read-only checks on 2026-08-31 confirmed the following on both GX10 systems:

- architecture: `aarch64`
- GPU: NVIDIA GB10
- Docker server: `29.1.3`
- Ollama: `0.32.1`
- installed model: `laguna-xs-2.1:q8_0`
- deterministic alias: `laguna-t0:latest`
- both names resolve to model blob SHA-256
  `235c73f038647ae496e25c7dea1ce362ca409fe9fdef34ccdf2880bfd5bcb2ce`

GX10-2 also had `glm-4.7-flash:q8_0` installed. Neither host listed
`nvidia/Nemotron-Flash-3B-Instruct`. Both listed older/smaller Nemotron Nano
models.

This inventory is time-sensitive and must be read back again when a run packet
is sealed.

## Native runtime constraint

The retained MARB v0.13 runtime and wheelhouse are `linux/amd64`. The exact
PyPI releases currently pinned by that runtime do not publish Linux aarch64
wheels for `cadquery-ocp==7.8.1.1.post1` or `vtk==9.3.1`. Reusing that
wheelhouse on a GX10 would therefore be the wrong architecture.

A native ARM64 closure is feasible without changing the existing x86 contract:

- conda-forge publishes CadQuery `2.7.0` as a noarch package;
- conda-forge publishes OCP `7.8.1.1` for `linux-aarch64`;
- conda-forge publishes VTK `9.3.1` for `linux-aarch64`.

The ARM64 lane must have its own exact package/build/hash lock, provenance,
calibration evidence, import/render checks, and immutable image digest. It must
not silently inherit the x86 native-library topology assertions.

## Required sequence

1. Finish, review, and merge the tracked nine-case MARB runtime smoke runner.
2. Build a native ARM64 CadQuery/CADCLAW package closure and validate it on a
   GX10.
3. Re-run CADCLAW compatibility calibration against the exact ARM64 closure.
4. Seal a new GX10-specific, no-provider R7-D runtime-smoke packet.
5. Obtain exact approval for that packet and consume its single attempt once.
6. If and only if R7-D passes, seal one local boxed benchmark using the already
   installed Laguna model and its full model digest.
7. Preserve model request/response, source/input hashes, runtime/image identity,
   timing, and generated artifacts; then run trusted MARB grading.
8. Review evidence before any results registration, board update, site rebuild,
   deployment, or public claim.

## Model and effort routing for Codex tasks

- Sol `xhigh`: fail-closed smoke runner, ARM64 runtime contract, sealed packet,
  and final merge/qualification review.
- Codex Spark `high` or `xhigh`: narrow mechanical edits, focused tests,
  inventories, and deterministic hash work, followed by Sol review.
- Terra `medium` or `high`: deterministic grading, evidence collation, and
  bounded documentation updates.
- Luna `medium` or `high`: high-volume clerical checks, concise copy, and simple
  visual artifacts.
- Reserve Sol `ultra` for a genuinely ambiguous final packet audit; it is not a
  default for every subtask.

The actual local benchmark generation uses Laguna or another explicitly pinned
local model on the GX10, not an OpenAI model session.

## Candidate model lanes

1. First local boxed candidate: installed `laguna-xs-2.1:q8_0` / `laguna-t0`.
2. Second local candidate after a separate packet: installed
   `glm-4.7-flash:q8_0` on GX10-2.
3. Nemotron Flash: monitor for a suitable update and verify its license before
   download or use. The current NVIDIA Nemotron Flash 3B Instruct model is not
   installed and its published license is non-commercial.
4. Grok: explicit, operator-initiated Cursor/Grok run only. Capture the sealed
   prompt and resulting artifacts for MARB post-hoc grading. Do not create an
   unattended paid API campaign without separate authorization and a supported
   programmatic interface.

## Claim boundary

Installed models and available ARM64 packages do not prove a qualified runtime
or a successful benchmark. Public wording must distinguish source merged,
runtime qualified, model run completed, trusted grading completed, results
registered, and site deployed.

## Primary references

- NVIDIA DGX Spark/GX10 hardware overview:
  <https://docs.nvidia.com/dgx/dgx-spark/hardware.html>
- Poolside Laguna XS 2.1 model card:
  <https://huggingface.co/poolside/Laguna-XS-2.1>
- Poolside Laguna S 2.1 NVFP4 GB10 guidance:
  <https://huggingface.co/poolside/Laguna-S-2.1-NVFP4>
- NVIDIA Nemotron Flash 3B Instruct model card:
  <https://huggingface.co/nvidia/Nemotron-Flash-3B-Instruct>
- CadQuery installation guidance:
  <https://cadquery.readthedocs.io/en/stable/installation.html>
- conda-forge OCP package:
  <https://anaconda.org/conda-forge/ocp>
- conda-forge CadQuery package:
  <https://anaconda.org/conda-forge/cadquery>
