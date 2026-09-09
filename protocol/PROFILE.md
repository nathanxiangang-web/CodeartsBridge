# Bridge Profile Extension Contract (v1)

This document defines the project-agnostic profile/policy engine for the codex-glm Bridge v1.2.
The engine lets each project declare its own phases, checks, roles, risk levels, approval gates,
timeouts, working-directory rules and evidence requirements without hardcoding any project
behavior into the bridge core.

## 1. Scope

- The engine is implemented in `scripts/Bridge.Policy.psm1` (PowerShell 7, no third-party
  dependencies, no network access).
- Profiles are JSON documents validated against `schemas/profile.schema.json` and enforced by
  the module's `Test-BridgeProfile` function.
- Safe example profiles live under `profiles/`. `profiles/cloudsite.example.json` is the first
  concrete profile; `profiles/generic.example.json` proves the engine is project-agnostic.
- Tests live in `tests/Test-Policy.ps1`.
- The bridge core (`scripts/bridge.ps1`) is intentionally NOT modified by this contract.
  Integration is opt-in via the minimal hook described in section 6.

## 2. Profile structure

A profile describes:

- `schemaVersion` (must be 1), `profileId`, `projectId`, `description`.
- `riskLevel`: one of `low`, `medium`, `high`, `critical`.
- `roles`: non-empty list of role names (`^[A-Za-z0-9_-]+$`).
- `defaultTimeoutSeconds`: optional integer 1..86400.
- `workingDirectory`: optional `{ mode, subpath }` where mode is `projectRoot`, `subpath` or `temp`.
- `phases`: non-empty array of phase objects.

A phase describes:

- `id` (`^[a-z0-9][a-z0-9._-]*$`), `description`, `roles`, `riskLevel`.
- `requiresApproval` (boolean) and `approvalGate` (name). When approval is required, the gate
  name must be present; the phase cannot execute until the gate is approved.
- `timeoutSeconds`, `onFailure` (`block`, `continue`, `warn`).
- `checks`: non-empty array of check objects.

A check describes:

- `id`, `description`, `roles`, `riskLevel`, `timeoutSeconds`.
- `command`: see section 3.
- `requiredEvidence`: list of file paths/globs the check must produce.
- `expectExitCode`: expected process exit code (default 0).
- `skip`: boolean to exclude the check from selection.

## 3. Command safety

A command is always an object with:

- `executable`: non-empty string (the program to run).
- `argv`: array of string arguments.
- `env`: optional array of environment entries (see section 4).
- `workingDirectory`: optional override.

The engine NEVER accepts an interpolated shell command string. `Test-BridgeProfile` rejects any
`command` that is a string, and `New-BridgeCheckStartInfo` throws if asked to build a StartInfo
from a string command. `ProcessStartInfo` is constructed with `UseShellExecute = false` and
arguments added via `ArgumentList.Add`, so each argument is passed verbatim without shell
interpolation.

## 4. Environment safety

Each environment entry is an object with:

- `name`: the environment variable name (`^[A-Za-z_][A-Za-z0-9_]*$`).
- `from`: either `allowlist` or `secret`.
- `secretRef`: required when `from = secret`, forbidden when `from = allowlist`.

The engine NEVER accepts a secret value in a profile. Any field named `value`, `secretValue`,
`literal` or `inline` on an env entry is rejected. For `allowlist` entries, the value is copied
from the host environment by name at StartInfo construction time. For `secret` entries, the
module records the `secretRef` but does NOT resolve or inline any value; the caller (bridge
runtime) is responsible for injecting the secret from a secret store. `New-BridgeCheckStartInfo`
returns `RequiredSecretRefs` so the caller knows what to inject without the profile ever
containing the secret.

## 5. Public functions

| Function | Purpose |
|---|---|
| `Get-BridgePolicyVersion` | Returns the schema version (1). |
| `Load-BridgeProfile -Path` | Reads and parses a profile JSON file. |
| `Test-BridgeProfile -Profile` | Validates a profile; returns `{ Valid, Issues }`. |
| `Assert-BridgeProfile -Profile` | Throws if the profile is invalid. |
| `Get-BridgePhase -Profile -PhaseId` | Returns a phase object or null. |
| `Select-BridgeGates -Profile -PhaseId [-Role]` | Returns checks for a phase, filtered by role, excluding skipped checks. |
| `New-BridgeCheckStartInfo -Check [-ProjectRoot] [-Environment]` | Builds a safe `ProcessStartInfo` plus `EnvAllowlist`, `ResolvedEnv`, `RequiredSecretRefs`. |
| `Test-BridgeCheckResult -Check -ExitCode [-EvidenceFiles]` | Evaluates exit code and required evidence; returns `{ Passed, ExitOk, MissingEvidence, Reasons }`. |
| `Get-BridgeApprovalGate -Profile -PhaseId [-ApprovedGates]` | Returns the unmet approval gate for a phase, or null if none/unblocked. |
| `Get-BridgeTimeout -Profile [-PhaseId] [-CheckId]` | Resolves the effective timeout (check > phase > default). |

All functions are pure/testable. `New-BridgeCheckStartInfo` accepts an optional `-Environment`
hashtable so tests can supply a controlled environment without touching the real host env.

## 6. Bridge integration hook (no core change)

The bridge core (`scripts/bridge.ps1`) is not modified. A future integration can use the engine
as follows without conflicting with Worker01 changes:

1. Load and validate a project profile with `Load-BridgeProfile` + `Assert-BridgeProfile`.
2. For each task phase, call `Get-BridgeApprovalGate`; if it returns a blocked gate, set the
   task to `REVIEW_REQUIRED` and do not execute the phase.
3. Call `Select-BridgeGates` for the task role/phase to get the ordered checks.
4. For each check, call `New-BridgeCheckStartInfo` and run the returned `StartInfo` with the
   bridge's existing captured-process runner. Inject `RequiredSecretRefs` from the secret store.
5. Call `Test-BridgeCheckResult` with the exit code and produced evidence files; honor the
   phase `onFailure` policy.

This hook is additive: the bridge continues to work without a profile, and a profile only
gates behavior when present.

## 7. Approval model

A phase with `requiresApproval: true` and an `approvalGate` name is blocked by default.
`Get-BridgeApprovalGate` returns a `{ PhaseId, Gate, Blocked, Reason }` object until the gate
name appears in the `ApprovedGates` list, after which it returns null (unblocked). The example
CloudSite deploy phase is approval-blocked by default and its command is a non-mutating dry-run,
so tests can never trigger a production mutation.

## 8. Constraints

- PowerShell 7, no third-party dependencies, no network access.
- No project-specific conditionals in the engine (the module contains no CloudSite reference).
- No credentials, live hostnames, mutable production commands or secret values in example
  profiles.
- Plain English ASCII only in all source, tests, profiles and deliverables.
