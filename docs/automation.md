# CATS WAR Automation

The runtime is driven by ADB screenshots and OmniParser. It does not depend on
the emulator window position or on the old machine's screen coordinates.

## Setup

1. Copy `config/accounts.example.json` to `config/accounts.json`.
2. Set `adb_path`, the emulator instance identifiers, and each ADB serial.
3. Start the OmniParser service at the configured `omni_parser_url`.
4. Confirm `adb devices` reports the configured devices as `device`.

The configured `launch_command` is optional. Its arguments support
`{instance}`, `{serial}`, and `{account}` substitutions. When omitted, the
runner only takes over already-connected devices. The runner starts instances
when the command is provided and leaves them running after completion.

## Commands

```text
catswar run --config config/accounts.json
catswar run --config config/accounts.json --select
catswar run --config config/accounts.json --account account-01
catswar run --config config/accounts.json --resume-run 20260820-120000
catswar inspect --adb-path D:/leidian/LDPlayer9/adb.exe
catswar stop --config config/accounts.json
```

The default concurrency is three accounts. Each account gets its own screenshots
under `output/screenshots/<account-id>` and an event log/checkpoint under
`output/runs/<run-id>-<account-id>`.

## Runtime behavior

The runner first completes the one-time join flow. It then rescans the six
buildings after every battle, computes the required vehicles as `floor(X / 2) +
1`, and skips locked, busy, or repairing vehicles. A round completes when no
usable vehicle target remains. `safety_mode` currently defaults to
`aggressive`; the setting is retained in the runtime contract for the guarded
mode that will add hard gates around high-risk actions.

When a state cannot be recognized before the configured timeout, that account is
paused independently and its latest screenshot, state, and error are retained
in the run directory. Other accounts continue to run.

Use `--resume-run` with a previous run id to load each account's checkpoint.
Retries are performed per account and do not consume another account's worker.
