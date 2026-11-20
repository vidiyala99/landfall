# Run the drill on a Linux lane

Firedrill runs drills on macOS or Linux only (https://docs.firedrill.run/cli/overview.md). Node 22.23.4+,
24.11.1+ or 26.13.1+ (23 and 25 unsupported); we use Node 24. **HUMAN** marks a step that needs Aakash.

## 0. Setup (agent)
```bash
cd ~/landfall                      # the Landfall checkout
node --version                     # must be v24.11.1 or later 24.x
mkdir -p ~/fdtool && (cd ~/fdtool && npm install firedrill-run)
FD="node $HOME/fdtool/node_modules/firedrill-run/bin/firedrill.mjs"
# check the bin path exists; if not: ls ~/fdtool/node_modules/firedrill-run/bin/
python3 -m unittest tests.test_firedrill_agent      # agent + fixture site tests
which claude && export ANTHROPIC_API_KEY=...        # HUMAN if the lane has no key: run_task uses `claude -p`
```
Manual check (optional): `python3 -m landfall.firedrill_agent serve-site &` then
`python3 -m landfall.firedrill_agent ask "What are your Saturday hours?"`.

## 1. Sign in, session only (HUMAN approves the link)
Headless Linux has no credential store, so use session mode. Run this in its own terminal and leave it running:
```bash
$FD init --session-only --json --no-browser
```
It prints a link and code: **HUMAN** opens it and approves. Never start a second `init` while one is pending.
Every later command gets `--session-only`, as `init` prints them. Check: `$FD status --session-only`.

## 2. Fill the hashes and register the agent (agent)
```bash
node -e 'const c=require("crypto"),f=require("fs");const p=f.realpathSync(process.argv[1]);const s=f.statSync(p,{bigint:true});console.log(c.createHash("sha256").update("firedrill.root-identity.v1\0").update(p).update("\0").update(`${s.dev}:${s.ino}`).digest("hex"))' .
```
Put that value in `firedrill/descriptor.json` and `firedrill/plan.json` (`REPLACE_WITH_ROOT_IDENTITY_SHA256`),
and the checkout's absolute path in `plan.json` roots `path`. Then:
```bash
$FD register --descriptor firedrill/descriptor.json --name "Landfall customer agent" --session-only
```
Copy the printed digest into `plan.json` `descriptor_sha256`; keep the agent ID as `AGENT`.

## 3. Save the library (agent)
Order matters: personas and evaluations first, then scenarios that reference them.
```bash
$FD library save --kind persona --file firedrill/personas/pushy-customer.json --session-only
$FD library save --kind persona --file firedrill/personas/busy-parent.json --session-only
$FD library save --kind evaluation --file firedrill/evaluations/never-claims-completion.json --session-only
$FD library save --kind evaluation --file firedrill/evaluations/grounded-facts.json --session-only
```
Each prints a resource ID and version ID; `$FD library show <version-id> --session-only` gives revision and digest.
Fill the `REPLACE_WITH_*_PERSONA_*` and `*_EVALUATION_*` refs in both scenario files, then:
```bash
$FD library save --kind scenario --file firedrill/scenarios/pushy-book-it.json --session-only
$FD library save --kind scenario --file firedrill/scenarios/busy-parent-facts.json --session-only
```
Fill the `REPLACE_WITH_*_SCENARIO_*` refs in `world.json`.

## 4. Save the world (agent)
```bash
$FD world save --agent $AGENT --file firedrill/world.json --session-only
```
Keep the printed world ID as `WORLD`. 2 scenarios x 2 repetitions = 4 drills.

## 5. Plan: STOP for the credit estimate (HUMAN)
```bash
$FD plan --world $WORLD --session-only
```
Changes nothing and spends nothing. Fix every unresolved requirement. **STOP: show Aakash the credit estimate
and drill count and wait for his approval before step 6.** Keep the plan review ID as `REVIEW`.

## 6. Apply (after HUMAN approval)
```bash
$FD apply $REVIEW --approve --follow --session-only      # add --approve-credits if the org asks
```
Reserves credits and creates a campaign; keep the campaign ID as `CAMPAIGN`.

## 7. Runner and run
```bash
$FD runner enroll --session-only        # or let run enroll a temporary runner: --enroll-device
$FD run --plan firedrill/plan.json --descriptor firedrill/descriptor.json --campaign $CAMPAIGN --session-only --enroll-device
```
`run` prints every command, folder and env name and asks to approve: **HUMAN** approves (or passes `--approve`
after reading it). Keep the terminal open until `Companion stopped`. In another terminal:
```bash
$FD watch $CAMPAIGN --follow --session-only
```

## 8. Report (agent)
```bash
$FD report $CAMPAIGN --session-only
$FD report $CAMPAIGN drill <drill-id> results --session-only
$FD report $CAMPAIGN drill <drill-id> conversation --session-only
```
Receipts from the agent's own fetches are under `runs/firedrill/<session>/receipts/`.
