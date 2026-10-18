# product-safety-desk

An independent hackathon entry for the AI Builder Cup 2026, not affiliated with or endorsed by any retailer, FSANZ or
the ACCC. CalmChaosRetail, its stores and every brand in its catalogue are fictional; recall notices on the test feed are
fictional and labelled FICTIONAL TEST.

The incident workflow (psd-agents, `app/`) is an ADK 2 graph workflow: Gemini drafts each incident, the run pauses for
a coordinator's approval, and policy code acts. The recall feeds, the scope job, the label and shelf checks and the
pages run in psd-api (`api/`). The project started from the `agents-cli` 1.10.0 ADK scaffold.

To try the live desk, [samples/](samples/README.md) has test shelf and label photos to send from the store page, and the
eval runs behind the drafting and shelf-reading figures.

## Project Structure

```
product-safety-desk/
├── app/                       # psd-agents: the incident workflow
│   ├── agent.py               # Workflow graph: nodes, edges and the approval pause
│   ├── fast_api_app.py        # FastAPI server: candidate push, desk routes, A2A
│   └── app_utils/             # A2A routes and service helpers
├── api/                       # psd-api: recall poller, relay, scope job, label check, coordinator and store pages (FastAPI, port 8081)
├── config/feeds.yaml          # Recall feeds the poller reads
├── transforms/                # Pub/Sub message transforms (JavaScript UDFs)
├── data/                      # truth.yaml, catalogue and supply generators, BigQuery loader, fixtures, test notices
├── sql/                       # BigQuery tables (ddl/), views (views/), recall matching and catalogue embedding
├── knowledge/                 # Policy, playbooks, references, tables, attested computations (OKF v0.2)
├── tools/                     # Bundle validator, staleness report, skill file generator
├── infra/                     # Cloud Build pipelines, Agent Engine setup
├── samples/                   # Test shelf and label photos for trying the live desk; eval results and traces
├── tests/                     # Unit, integration, BigQuery SQL and end-to-end tests; the drafting eval
├── AGENTS.md                  # AI-assisted development guide
└── pyproject.toml             # Project dependencies
```

> 💡 **Tip:** Use [Antigravity CLI](https://antigravity.google/) for AI-assisted development - project context is pre-configured in `AGENTS.md`.

## Requirements

Before you begin, ensure you have:
- **uv**: Python package manager (used for all dependency management in this project) - [Install](https://docs.astral.sh/uv/getting-started/installation/) ([add packages](https://docs.astral.sh/uv/concepts/dependencies/) with `uv add <package>`)
- **agents-cli**: Agents CLI 1.10.0 - Install with `uv tool install "google-agents-cli~=1.10.0"` (the version this project was scaffolded and pinned with)
- **Google Cloud SDK**: For GCP services - [Install](https://cloud.google.com/sdk/docs/install)


## Quick Start

Install `agents-cli` and its skills if not already installed:

```bash
uvx google-agents-cli setup
```

Credentials: Application Default Credentials only, no API key. `PSD_DEV_UI=1` in `.env` serves the ADK dev UI
from `app/fast_api_app.py` for local development; never set it on a public deploy. Run `gcloud auth application-default login`, then copy
`.env.example` to `.env` and set `GOOGLE_CLOUD_PROJECT` (keep `GOOGLE_GENAI_USE_ENTERPRISE=true`). `.env` is never
committed. The agent spec for coding agents is [.agents-cli-spec.md](.agents-cli-spec.md).

Install required packages:

```bash
agents-cli install
```

Test the agent with a local web server:

```bash
agents-cli playground
```

You can also use features from the [ADK](https://adk.dev/) CLI with `uv run adk`.

## Commands

| Command              | Description                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------- |
| `agents-cli install` | Install dependencies using uv                                                         |
| `agents-cli playground` | Launch local development environment                                                  |
| `agents-cli lint`    | Run code quality checks                                                               |
| `agents-cli eval`    | Evaluate agent behavior (generate, grade, analyze, and more — see `agents-cli eval --help`) |
| `uv run pytest tests/unit tests/integration` | Run unit and integration tests                                                        |

Deployment and CI/CD are set up as described under [Deployment](#deployment), not with `agents-cli infra`.

---

## Development

Edit your agent logic in `app/agent.py` and test with `agents-cli playground` - it auto-reloads on save.

### Synthetic data

The desk reads a fictional CalmChaosRetail world from BigQuery, generated from `data/truth.yaml`. Create the datasets once:

```bash
bq --location=us-central1 mk --dataset <your-project-id>:psd
```

```bash
bq --location=us-central1 mk --dataset <your-project-id>:psd_test
```

Load the data, and reload it before a rehearsal, since the world is timed from the load:

```bash
uv run python data/load_truth.py --dataset psd
```

`uv run pytest tests/sql` checks the attested lineage against the truth tables. Offline unit tests read
`data/fixtures/evidence/`. After changing the generators, rewrite those fixtures with
`uv run python data/write_fixtures.py`.

### Recall trigger (psd-api)

The poller reads the FSANZ feed and the test feed, Gemini extracts each notice in a Pub/Sub transform, and the scope job
matches it to the catalogue and raises a candidate when stores or online orders hold the batch. Sources and terms are
in [DATA_SOURCES.md](DATA_SOURCES.md).

The transforms' constants come from the knowledge bundle. After a policy or model change, regenerate them, and write
the gcloud transform files for your project (they stay out of git):

```bash
uv run python tools/gen_transforms.py --project <your-project-id>
```

Create the trigger's tables and views (data is not touched):

```bash
uv run python data/load_truth.py --dataset psd --ddl-only
```

Run the incident workflow and psd-api side by side. Locally, psd-api consumes the push subscriptions by streaming pull
(`PSD_LOCAL_PULL=1`) and runs the poll and the scope job on their schedules (`PSD_LOCAL_SCHEDULE=1`):

```bash
uv run uvicorn app.fast_api_app:app --port 8000
```

```bash
PSD_LOCAL_PULL=1 PSD_LOCAL_SCHEDULE=1 uv run uvicorn api.main:app --port 8081
```

Publish a fictional notice to the test feed, then poll now instead of waiting for the schedule:

```bash
uv run python data/gen_notices.py --publish yoghurt_listeria
```

```bash
curl -X POST http://127.0.0.1:8081/internal/poll-recalls
```

`POST /internal/scope` runs the scope job the same way. It reads the match rule and the recall response, so it stops
until those concepts are reviewed (see below).

### Label check (store page)

On the store page (`/store` on psd-api, opened from the store link the coordinator page hands out), an associate
photographs the back of a pack. Gemini transcribes the label; code matches it to the catalogue and compares it with the online listing
and the latest supplier spec by the label rules. A high or critical finding raises a label incident on the coordinator
page, and the store's hold tasks appear back on the store page.

Render the label photos for the four label fixtures and eight clean packs, flat, angled and under glare:

```bash
uv run python data/gen_labels.py
```

They land in `artifacts/labels/` with a `manifest.json` of the findings each should give. The photos the store page
sends are kept in `gs://<project>-psd-photos` (or `PSD_PHOTOS_BUCKET`) for 7 days. The label check also reads
`/references/allergens.md`, so that concept needs its review first.

### Shelf photos (store page)

A store closes each hold or pull task with a photo of the shelf, from the Photograph the shelf button on the task's
card. Gemini reports whether a unit of the product is still visible and how sure it is; the shelf check policy decides clear, not clear (the task is issued again) or retake. Until
`/policy/shelf-check.md` is reviewed the store page refuses shelf photos and says why.

Render shelf photos for the yoghurt and dinosaur recalls, each present, clear, blurred, and present under a sign saying
the shelf was checked clear:

```bash
uv run python data/gen_shelves.py
```

They land in `artifacts/shelves/` with a `manifest.json` of the verdict each should give.

### Sessions and incident records

On Cloud Run, psd-agents keeps each incident's paused run in Agent Platform Sessions and its records (incidents, tasks,
outbox, audit) in Firestore, so a restart or a redeploy loses neither. Find or create the Agent Engine instance, which
runs no agent code, and note the id it prints:

```bash
uv run python infra/agent_engine.py --project <your-project-id>
```

Then set `GOOGLE_CLOUD_AGENT_ENGINE_ID`, `GOOGLE_CLOUD_AGENT_ENGINE_LOCATION=us-central1` and `PSD_STORE=firestore` on
psd-agents. Without them, as in tests and local runs, both stay in memory.

The same instance's Memory Bank keeps the observations written when an incident closes; the script gives it
`gemini-3.8-flash` and `gemini-embedding-2` from the `us` multi-region. An observation whose generation failed keeps its
facts in its memory link, and `POST /desk/api/memory/retry` (optionally `?limit=N`, oldest first) generates the failed
ones again.

### Approving on the desk

The coordinator page has six views kept in the URL hash: Home, then Notices, Label checks, Incidents, Learned and
Scoreboard in the order the work flows. Home shows the incidents waiting for a decision, the ones whose shelves are being verified,
the feeds with the latest notice and label check, and three headline figures, all from the data the other views poll.
Incidents are a list beside the chosen incident's detail; on a phone, a tapped incident opens on its own with a Back
control. The
detail shows the narrative, the proposed or approved actions, considerations, evidence with its receipts, the customer
message and the store tasks. An incident awaiting approval offers Approve, Edit then approve and Dismiss (with a reason)
in a bar at the foot of its detail. Edit then approve lists the proposed store actions (drop a store, turn a hold into a
pull, add an optional store), the checkout block and the texts; an edit that policy refuses, such as dropping the
checkout block on a critical recall without a reason, comes back with the reason before anything runs. After approval
the detail shows the approved version and the edits. Show trace lists the run's steps from its session: each node's
route and state keys, the draft, every pause and every reply.

### Scoreboard

`GET /metrics` on psd-api, and the Scoreboard panel on the coordinator page, show ten tiles: from notice to candidate
and from candidate to approval, customers messaged, shelves clear, stores verified, listing fixes, notice outcomes, label
findings, published versus landed, and detection quality against the truth tables. Every value is what a reviewed
attested computation in `knowledge/computations/` returned, shown with its receipt id; a tile whose metric or
computation is unreviewed shows a dash until a person verifies both.

The incident tiles read the desk's records in BigQuery: psd-agents appends every version it writes to Firestore to
`desk_records`, which `data/load_truth.py --dataset psd --ddl-only` creates with its views. `PSD_DESK_RECORDS=off`
keeps them in Firestore only.

### Learned tab and promotion

The desk's Learned tab lists the observations Memory Bank holds, by scope, with the incidents each came from. A
coordinator can delete one, or verify and promote it. A promotion is a GitHub pull request on `PSD_GITHUB_REPO`
against `PSD_GITHUB_BASE` (default `main`), labelled `promotion`, that changes only `knowledge/learned/`:
- the scope's note (`suppliers/`, `products/`, `stores/` or `playbook/coordinator-practice.md`), with the fact, the
  incidents as sources and footnotes, the coordinator as verifier, and the chosen `stale_after`;
- `learned/index.md` and `learned/log.md`.

The observation is left out of drafts while the pull request is open. `.github/CODEOWNERS` lets these pull requests
merge without an owner's review once the pull-request check passes. After a deploy, `POST /internal/promotions/settle`
on psd-agents with `{"deployed_sha": ...}` deletes each promoted memory whose merge is deployed, and returns a closed,
unmerged one to the drafts.

Promotion needs a token that can push branches and open pull requests on the repository, in `PSD_GITHUB_TOKEN` (Secret
Manager `psd-github-token` on Cloud Run). Without it, the tab says promotion is unavailable; listing and deleting still
work.

### Model Armor on the drafter

psd-agents screens each drafter's evidence and draft with ADK's `ModelArmorPlugin` when `MODEL_ARMOR_PROMPT_TEMPLATE`
and `MODEL_ARMOR_RESPONSE_TEMPLATE` name templates in the desk's region (`PSD_REGION`, us-central1). Without them, as
in tests and local runs, nothing is screened. A draft makes one Model Armor call each way and no extra Gemini call. A
blocked prompt leaves the incident `blocked` and undrafted; a blocked draft is redrafted with the reason; a failed
screening call lets the draft go on, recorded as not screened. The incident card shows the verdicts.

### Tests that call Gemini

Every Gemini call is billed, so the default test run makes none. Integration tests and BigQuery tests that call Gemini
(directly, or through `AI.EMBED` and `AI.IF`) run only with `PSD_GEMINI_TESTS=1`; the label-reading eval runs only with
`PSD_LABEL_EVAL=fixtures` (4 calls) or `PSD_LABEL_EVAL=all` (36 calls); the shelf-reading eval only with
`PSD_SHELF_EVAL=yoghurt` (4 calls) or `PSD_SHELF_EVAL=all` (8 calls).

### Drafting eval

`tests/eval/datasets/basic-dataset.json` holds 16 cases: a recall for each hazard type with a playbook and a label
check for each label rule. `data/gen_eval_cases.py` picks them from the generated world and writes their stand-ins,
their evidence packs and the dataset. Each case carries a reference built from its evidence and the policy's
proposal, so a reference states only facts a correct card must agree with. Run the cases offline, with fixture
evidence. This makes about 32 to 50 Gemini calls: a draft and a judge call per case, plus any redrafts.

```bash
PSD_EVIDENCE_SOURCE=fixtures agents-cli eval run
```

```bash
uv run python tools/eval_gate.py
```

The gate passes when all of these hold:
- the rubric mean is at least 4 of 5;
- the trajectory metric is 1.0: every step in order, the approval pause last, nothing executed before it;
- every draft is a complete IncidentText;
- no case errored.

A draft that cites a store, a batch or lot code, or a count of stores, orders or units that the evidence lacks is
redrafted, and it fails the run after two retries.
So a trajectory of 1.0 also means no invented identifiers.

### End-to-end test

`tests/e2e/test_recall_e2e.py` runs against a desk that is up: local, or the deployed psd-api with its passcode. It
publishes the yoghurt_listeria notice, drives the poll and the scope job, and passes when one incident pauses for
approval with 14 stores, 212 units and 37 orders, all attested. It makes about 4 to 9 Gemini calls.

```bash
PSD_E2E=1 PSD_E2E_URL=https://<psd-api URL> PSD_E2E_PASSCODE=<passcode> uv run pytest tests/e2e
```

### Agent analytics and operational metrics

With `PSD_ANALYTICS_DATASET` set, psd-agents writes every run to `<dataset>.agent_events` through ADK's BigQuery
Agent Analytics plugin. The rows cover each step, model call, approval pause and error, with a view per event type,
in the desk's region. An incident's session id is its incident id, so one `session_id` filter returns its whole
history.

The rows are best-effort telemetry, not the audit log. Decisions and executor writes are audited in the desk's store.

`tools/ops_report.py` checks design §18's operational targets on those rows: draft p95 under 20 s, and Memory Bank
retrieval timeouts under 2%.

### Knowledge and policy

Every severity, time target, threshold and label rule lives in `knowledge/`, never in code. The workflow uses a concept
only when it is `status: stable`, has a `verified` entry by a `human:` reviewer and is not past `stale_after`. A policy
that fails this stops the run; a playbook that fails it is left out of the prompt.

To change a value:
1. Edit the concept in `knowledge/policy/` or `knowledge/references/`.
2. Record your review in the concept's `verified` list, as `- { by: "human:<you>", at: <UTC instant> }`.
3. Add an entry to `knowledge/log.md`.
4. Run the checks:

```bash
uv run python tools/okf_validate.py knowledge
```

```bash
uv run python tools/gen_skill_refs.py
```

```bash
uv run pytest tests/unit
```

`tools/stale_report.py` lists concepts past `stale_after` and policies due within 30 days.

## Deployment

One image (`Dockerfile`) serves two Cloud Run services in us-central1:
- **psd-agents** runs the image's command, the incident workflow (`app.fast_api_app`). It is private.
- **psd-api** runs `uvicorn api.main:app`: the feeds, the scope job, the desk and store pages, and `/metrics`.

The image carries `knowledge/`, so deploy only a tree whose edited concepts carry a fresh `verified` entry.

### By hand

```bash
gcloud run deploy psd-agents --source . --region=us-central1
```

```bash
gcloud run deploy psd-api --source . --region=us-central1
```

A deploy that names only the source or image keeps each service's other settings: command, service account,
environment and flags.

Optional settings on psd-agents:
- `PSD_GITHUB_REPO` (`owner/name`) and `PSD_GITHUB_BASE` (`main`).
- `PSD_GITHUB_TOKEN`, from Secret Manager, to open promotion pull requests.
- `PSD_ANALYTICS_DATASET`, for agent analytics.
- The Cloud Build service account in `PSD_TRIGGER_SERVICE_ACCOUNTS`, so the build can settle promotions.

### Cloud Build

`infra/cloudbuild.yaml` (trigger `psd-main`, pushes to `main`) runs these steps:
1. Validates the bundle and checks every generated file for drift.
2. Runs lint, the unit tests and the BigQuery SQL tests.
3. Passes the drafting eval gate.
4. Builds the image once, with the commit as `PSD_KNOWLEDGE_VERSION`.
5. Deploys both services and updates the Pub/Sub transforms.
6. Settles promotions.

`infra/cloudbuild-pr.yaml` (trigger `psd-pr`, pull requests into `main`) runs the promotion-path rule, the bundle
checks, lint and unit tests, with no Gemini call and no deploy.

One-off setup, by the project owner:

```bash
gcloud services enable cloudbuild.googleapis.com artifactregistry.googleapis.com
```

```bash
gcloud artifacts repositories create psd --repository-format=docker --location=us-central1
```

```bash
gcloud iam service-accounts create sa-psd-build --display-name="Product Safety Desk build"
```

Grant `sa-psd-build` these roles:
- `roles/run.admin`, `roles/artifactregistry.writer`, `roles/aiplatform.user` (the eval), `roles/pubsub.editor` (the
  transforms) and `roles/logging.logWriter` on the project;
- `roles/iam.serviceAccountUser` on the two runtime service accounts;
- `roles/bigquery.jobUser` and `roles/bigquery.user` (the SQL tests make and delete their own dataset), with
  `roles/bigquery.dataEditor` on `psd_test` and `roles/bigquery.dataViewer` on `psd`;
- `roles/run.invoker` on psd-agents.

Then connect the GitHub repository to Cloud Build in the console; the repository owner approves the Cloud Build app.
Create the two triggers on that connection:
- **psd-main:** branch `^main$`, config `infra/cloudbuild.yaml`, service account `sa-psd-build`, substitution
  `_AGENTS_URL=<psd-agents URL>`. Its included files are `app/**`, `api/**`, `knowledge/**`, `transforms/**`,
  `sql/**`, `config/**`, `data/**`, `tests/**`, `Dockerfile`, `pyproject.toml` and `uv.lock`, so a docs-only push
  builds nothing.
- **psd-pr:** pull requests into `^main$`, config `infra/cloudbuild-pr.yaml`.

Each psd-main build that runs the eval makes about 32 to 50 Gemini calls.

### Firebase Hosting and sign-in

`firebase.json` serves `api/static` (the desk at `/` and `/desk`, the store page at `/store`). It rewrites `/desk/api/**`,
`/store/api/**` and `/metrics` to psd-api on Cloud Run, so the pages stay same-origin.

On Firebase Hosting the pages behave differently from psd-api's own:
- **Desk:** coordinators sign in with Google or with email and password instead of the passcode. psd-api accepts a
  Firebase ID token only from an account with the `coordinator` claim, and records its email as the actor of every
  decision and promotion. Until a coordinator signs in, the page shows the sign-in card alone; signing out clears
  everything it read, and an account without the role is signed out again. A token psd-api could not check, because
  Google's signing keys were unreachable, gets a 503 rather than a 401, so the page shows the error and keeps the
  coordinator signed in.
- **Store page:** it exchanges its signed link for a Firebase custom token naming its store, under a Firebase app of its
  own, so a store page opened from the desk leaves the coordinator signed in.
- **Live updates:** both pages listen to Firestore (`psd_incidents`, `psd_tasks`, the default database) and refresh
  when a record changes. `firestore.rules` lets a coordinator read incidents and tasks, and a store read its own
  tasks; nothing else can be read, and no client writes.

The psd-api pages keep the passcode and polling; there too the desk shows only its gate until the passcode is accepted.

One-off setup, by the project owner:

```bash
firebase projects:addfirebase <project>
```

Then enable the Email/Password and Google sign-in providers in the Firebase console, under Authentication. Let psd-api
mint store tokens; it also needs `GOOGLE_CLOUD_PROJECT` set, to check ID tokens:

```bash
gcloud iam service-accounts add-iam-policy-binding sa-psd-api@<project>.iam.gserviceaccount.com --member=serviceAccount:sa-psd-api@<project>.iam.gserviceaccount.com --role=roles/iam.serviceAccountTokenCreator
```

Grant the coordinator role. `--create` makes an email-and-password account, such as a demo account for judges, and
asks for its password. A Google account signs in on the desk once before it can be granted.

```bash
uv run python tools/grant_coordinator.py <email> --create --project <project>
```

```bash
firebase deploy --only hosting,firestore:rules --project <project>
```

A Hosting rewrite to Cloud Run times out after 60 s. An action that runs longer still finishes, and the page updates
from Firestore when it does. Examples are the scope job, and a last shelf verdict that closes an incident and writes
its observations.

## Observability

psd-agents sends OpenTelemetry traces and logs to Cloud Trace and Cloud Logging. Agent analytics (above) writes each
run to BigQuery.

## A2A

psd-agents also serves the [A2A Protocol](https://a2a-protocol.org/) at `/a2a/app`, from the scaffold. On Cloud Run the
service is private, so only callers granted `roles/run.invoker` reach it. The
[A2A Inspector](https://github.com/a2aproject/a2a-inspector) can test it against a local run.

## License

The code is licensed under the Apache License 2.0; see [LICENSE](LICENSE). It started from the `agents-cli` ADK
scaffold (Apache-2.0, Google LLC). Third-party content, such as FSANZ recall notices, stays under its owners'
terms, listed in [DATA_SOURCES.md](DATA_SOURCES.md).
