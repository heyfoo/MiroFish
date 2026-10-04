# Building a finance narrative app on MiroFish

This guide is for building a product on top of MiroFish that rehearses how a financial crowd reacts to a real document: an earnings release, a central-bank note, a rumor, a short report. The product is a narrative simulator. It is not a pricing engine, an order book, or a source of trading signals.

MiroFish already does the hard part. It turns seed text into a knowledge graph, turns graph entities into agents with personas, runs those agents on a Twitter-like tape and a Reddit-like forum, then writes a report and lets you interview any agent. Your app is the finance-shaped shell around that pipeline: the scenario, the cast, the question, and the way you present the result.

Read this once before writing product code. The control surface is smaller than the config files suggest, and a few tempting fields do nothing at runtime.

## 1. What "top tier" means here

A strong version of this app has four properties.

1. **The cast is specific.** A buy-side PM, a sell-side analyst, a short seller, a wire reporter, and a retail forum do not share one persona. They are separate entities in the graph, with bios the model actually sees.
2. **The shock is a document, not a vibe.** Agents react to the filing or the headline you uploaded, plus one explicit opening post. They do not invent the facts of the case.
3. **The feed is personalized.** Who sees which post changes who replies. Random ranking makes a fund and a day trader react to the same arbitrary sample. That is not good enough for this product.
4. **The answer is a distribution of narratives, with quotes.** "Here is how the specialist press, the long-only crowd, and the retail forum each moved, and here is an agent saying why." A single bullish/bearish score is a dashboard garnish. It is not the product.

Speed comes from where the LLM runs and how many calls you make. Quality comes from the model, the personas, and the feed ranker. Those are different budgets. Section 4 sets both.

## 2. What MiroFish will not do

Be explicit in the product, or users will treat a story as a price.

| You can rehearse | You cannot get from this engine |
|---|---|
| How different market roles talk about a filing | A price, a return, or a volatility number |
| Which narrative catches on, and who amplifies it | An order book, a spread, or a fill |
| What a specific agent says when interviewed after the run | A recommendation to buy or sell |
| How the story differs if the opening post changes | A calibrated probability of an earnings beat |

The two platforms are social surfaces, not venues:

- **Twitter** is the fast public tape. Headlines, one-line takes, quote-posts, follows.
- **Reddit** is the slower forum. Longer posts, comments, votes, search.

Map them to finance roles however you like (wire tape vs. specialist forum). Do not map them to exchanges.

Agent fields that look like finance controls but are **not read by the simulation loop** today:

- `stance`
- `sentiment_bias`
- `influence_weight`
- `posts_per_hour` and `comments_per_hour`
- `event_config.scheduled_events`, `hot_topics`, and `narrative_direction`

The config generator writes them into `simulation_config.json`. The runners in `backend/scripts/` never consult them. Putting "stance: opposing" on a short seller does not make that agent oppose anything. The persona text does, because that text is what the LLM sees. If you need those fields to change behavior, you have to teach the runner to use them. Until then, do not build UI that pretends they work.

Fields the loop **does** use:

- The persona and bio on the OASIS profile.
- `activity_level` and `active_hours` on each agent.
- `time_config.agents_per_hour_min`, `agents_per_hour_max`, peak and off-peak hours, `minutes_per_round`, and `total_simulation_hours`.
- `event_config.initial_posts` (published at round 0).
- The Twitter recommender (`OASIS_TWITTER_RECSYS`).
- Which LLM each platform calls.

## 3. Architecture

Keep MiroFish as the simulation service. Build the finance app as its own frontend and a thin backend that owns users, scenarios, and saved results. Do not fork the agent loop into the product repo.

```
finance-app/
  web/            scenario builder, run view, narrative report
  api/            auth, portfolios of scenarios, result snapshots
mirofish/
  frontend/       the existing lab UI (keep it for debugging)
  backend/        graph, profiles, OASIS run, report, interview
  uploads/        seed files, profiles, sqlite, actions.jsonl
```

The finance API stores a scenario and then calls MiroFish. It does not reimplement OASIS.

```
User picks a company and a question
        |
        v
Seed documents + simulation_requirement
        |
        v
POST /api/graph/ontology/generate
POST /api/graph/build
        |
        v
POST /api/simulation/create
POST /api/simulation/prepare
        |
        v
Edit simulation_config.json (opening post, who is awake, round cap)
        |
        v
POST /api/simulation/start
        |
        v
Poll run-status. When the run is terminal and Zep ingestion is done:
POST /api/report/generate
        |
        v
Interview the few agents the report says mattered
POST /api/simulation/interview
        |
        v
Snapshot posts, interviews, and the report into your own database
```

MiroFish keeps state on local disk under `backend/uploads/` and in Zep Cloud. That is fine for a single operator. A multi-tenant product needs one simulation directory and one Zep graph per scenario, and it needs to treat the MiroFish process as a worker, not as a shared scratchpad. Two runs writing the same `simulation_id` will clobber each other.

The lab UI at port 3000 is for you. Customers should never see the raw graph force-layout or the uncapped action timeline. Your product reads:

- `GET /api/simulation/<id>/posts` and `/comments` (SQLite, the actual posts)
- `GET /api/simulation/<id>/actions?limit=&offset=` (the full action log, paged)
- `GET /api/simulation/<id>/agent-stats`
- `GET /api/report/<report_id>/sections`
- `POST /api/simulation/interview` while the environment is still open

`GET /api/simulation/<id>/run-status/detail?tail=300` is a live ticker for the lab UI. It is not the historical record. Do not build analytics on it.

## 4. Quality and speed together

Each agent turn is one LLM call. Wall-clock time is about:

```
(agents woken per round) x (rounds) x (model latency) / (concurrency)
```

The feed ranker is a small part of that once it is loaded. The 1GB `twhin-bert` model is what exhausts an 8GB machine. The random ranker is what throws away finance quality. Use the middle one.

Production `.env` for this app:

```env
# Strong, fast hosted model. This is the quality of every post and reply.
LLM_API_KEY=...
LLM_BASE_URL=https://your-fast-provider/v1
LLM_MODEL_NAME=a-strong-fast-model

# Optional second provider for the Reddit crowd, so the two platforms
# do not share one rate limit. Twitter always uses LLM_*.
# Reddit uses LLM_BOOST_* when the key is set, and falls back to LLM_*.
LLM_BOOST_API_KEY=...
LLM_BOOST_BASE_URL=https://your-cheap-fast-provider/v1
LLM_BOOST_MODEL_NAME=a-smaller-fast-model

# Cloud endpoint: leave concurrency at 30.
# A localhost URL silently drops this to 2, which is correct for Ollama
# and fatal for a product that is supposed to feel fast.
LLM_MAX_CONCURRENCY=30

# Semantic feed, about 90MB. Do not use "random" for this product.
# "twhin-bert" is the original 1GB ranker. The extra quality over MiniLM
# is small next to the memory cost. Spend that budget on the LLM.
OASIS_TWITTER_RECSYS=twitter

ZEP_API_KEY=...
```

How to spend the two budgets:

| Goal | Do this |
|---|---|
| Posts that sound like the role | A strong model on Twitter (`LLM_MODEL_NAME`). The persona is in the prompt; a 3B local model will flatten a PM and a journalist into the same voice. |
| A cheap crowd | A smaller fast model on Reddit via `LLM_BOOST_*`. |
| Personalized feeds | `OASIS_TWITTER_RECSYS=twitter`. |
| A run that finishes in minutes, not hours | 12 to 24 simulated hours, `minutes_per_round` of 60, and a hard `max_rounds` between 12 and 24. Wake 5 to 15 agents a round, not the whole cast. |
| The report can see what just happened | `enable_graph_memory_update: true` on start. Wait until runner status is `completed` or `stopped`. A report requested while Zep is still ingesting returns 409. |
| An 8GB laptop | Debug here with a 3B local model, concurrency 2, one platform, and under 40 rounds. Do not demo the product from that box. Run the simulation worker on the fast API. |

CPU versus CUDA PyTorch does not change the text. On Linux, `uv sync` installs the CPU build because the default ranker no longer needs a GPU. MiniLM still runs on CPU and is small enough that this stays true.

## 5. The world model

You do not hand-code agents. You upload documents and describe the question. The ontology step asks the LLM which entity types and relationship types the graph should contain. If the requirement is vague, you get vague people.

Write the requirement so the types you care about are named in the prompt. A usable finance cast:

| Entity type | What they are for | How they should talk |
|---|---|---|
| `Issuer` | The company or the sovereign | Speaks only from the document |
| `Executive` | CEO, CFO, IR | Bound by what the filing actually says |
| `SellSideAnalyst` | The note that everyone else reacts to | Model, estimate, and what would change the rating |
| `LongOnlyPM` | The slow, large holder | Portfolio fit, thesis, what would make them sell |
| `HedgeFundPM` | The fast holder | Positioning, crowding, what the print means for the book |
| `ShortSeller` | The opposing narrative | The hole in the story, not a cartoon villain |
| `WireReporter` | The tape | What is new, what is a restatement, who they still need |
| `RetailForum` | The aggregated forum voice | Concrete, limited, often wrong in a specific way |
| `Regulator` or `CentralBank` | Only when the scenario is policy | Mandate and language, not a market call |

Aim for 15 to 40 entities. Below that, the crowd has no one to react to. Above that, profile generation and every round get expensive, and the graph view becomes noise. Institutions you care about should be real names from the documents ("the company's CFO"), not "Investor 7". Group entities ("retail holders of the stock") are allowed. The profile generator already distinguishes a person from a group. Use a group when you want a chorus, and a person when you want a quote.

Relationships worth extracting: `covers`, `holds`, `competes_with`, `regulates`, `reports_on`, `reports_to`. These land in Zep and show up in the report tools. They do not, by themselves, change who is followed inside OASIS. Follows emerge during the run.

Persona quality is the highest-leverage edit you can make. After `prepare` finishes, open `reddit_profiles.json` and `twitter_profiles.csv` in the simulation directory and read ten bios. If a short seller's bio could belong to a retail trader, regenerate with `force_regenerate: true` or rewrite that profile before starting. The run will not fix a bland persona.

## 6. Seed documents

The graph is only as factual as the text you upload. Accepted types are PDF, Markdown, and plain text, up to 50MB.

For one scenario, upload a small packet, not a data room:

1. The primary document. The 8-K, the earnings release, the FOMC statement, the short report.
2. One prior comparison. Last quarter's release, or the previous statement. Agents need a baseline or every number looks like news.
3. Optional: one reputable news recap, clearly labeled as secondary.

Do not upload a year of chat logs. Chunking sends that text to Zep, profile generation re-reads it, and the agents start citing forum lore as fact.

In the requirement, state the question as a rehearsal, and state the facts the agents must not invent:

```
Rehearse the first 24 hours of public reaction to this earnings release.
Cast: the CFO, two sell-side analysts who cover the company, one long-only PM,
one hedge-fund PM, one short seller, two wire reporters, and a retail-holder forum.
Question: which claim in the release becomes the argument, and which roles
reject it? Agents may only treat numbers that appear in the uploaded documents
as facts. They should say when they do not know.
```

That string is `simulation_requirement` on ontology generate. It is also the intent the report agent answers later. Write it as the question the product is asking. A generic "simulate the market" requirement produces a generic crowd.

## 7. The pipeline

All routes below are on the MiroFish backend, default `http://localhost:5001`. Long steps return a task id. Poll them. Do not block a web request on profile generation.

### 7.1 Ontology

`POST /api/graph/ontology/generate` as `multipart/form-data`.

| Field | Required | Role |
|---|---|---|
| `files` | yes | One or more pdf, md, or txt |
| `simulation_requirement` | yes | The question and the cast, as in section 6 |
| `project_name` | no | Shown in the lab UI |
| `additional_context` | no | Extra constraints that are not in the files |

Response `data.project_id` and `data.ontology`. Read the ontology before building. If `Issuer` or `SellSideAnalyst` is missing, the documents did not support them or the requirement was too soft. Fix the requirement and create a new project. Do not hope the simulation invents the missing role well.

### 7.2 Graph

`POST /api/graph/build`

```json
{
  "project_id": "proj_xxxx",
  "chunk_size": 500,
  "chunk_overlap": 50
}
```

Poll `GET /api/graph/task/<task_id>` until `status` is `completed`. Then `GET /api/graph/data/<graph_id>` to confirm the nodes you care about exist. `GET /api/simulation/entities/<graph_id>/by-type/<entity_type>` is the check you automate: fail the scenario if the CFO node is absent.

Zep's free monthly quota covers short rehearsals. A product that builds many graphs a day needs a paid Zep plan, or the build step starts failing mid-packet.

### 7.3 Create and prepare

`POST /api/simulation/create`

```json
{
  "project_id": "proj_xxxx",
  "enable_twitter": true,
  "enable_reddit": true
}
```

Turn a platform off when you are debugging. One platform halves the LLM bill and the memory.

`POST /api/simulation/prepare`

```json
{
  "simulation_id": "sim_xxxx",
  "use_llm_for_profiles": true,
  "parallel_profile_count": 5,
  "force_regenerate": false
}
```

`entity_types` is optional. Pass it when the graph contains people who should not be in this rehearsal (a historical CEO, a peer-company IR account). Profiles are generated in parallel. If `LLM_MAX_CONCURRENCY` is set, the default parallelism is capped by it.

Poll `POST /api/simulation/prepare/status` with `{ "simulation_id": "sim_xxxx" }` until the simulation is ready. Inspect:

- `GET /api/simulation/<id>/profiles?platform=twitter`
- `GET /api/simulation/<id>/config`

### 7.4 Shape the shock before you start

Prepare writes `backend/uploads/simulations/<simulation_id>/simulation_config.json`. Edit it on disk. This is the supported way to inject the "what if". There is no separate shock API.

Set the clock so a session is a day, not a week:

```json
"time_config": {
  "total_simulation_hours": 24,
  "minutes_per_round": 60,
  "agents_per_hour_min": 5,
  "agents_per_hour_max": 12
}
```

That is 24 rounds. Pass `max_rounds` on start anyway, so a later edit of `total_simulation_hours` cannot blow the budget.

Raise `activity_level` and widen `active_hours` for the CFO, the analysts, and the wire reporters. Leave the retail forum on a narrower window. This is the lever that actually decides who speaks.

Replace `event_config.initial_posts` with the shock, spoken by the agent who would really say it. `poster_agent_id` is the profile `user_id`, which matches `agent_id` in `agent_configs`.

```json
"event_config": {
  "initial_posts": [
    {
      "poster_agent_id": 3,
      "content": "Earnings are out. Revenue 4.2bn vs our preview, gross margin 61%. The line I am stuck on is the cut to full-year operating-income guide. Full release is the document we were given."
    }
  ]
}
```

The content should point at the document, not add a number that is not in it. Round 0 publishes these posts before anyone acts. Later rounds, agents only see them if the recommender or a follow puts them in the feed. With `OASIS_TWITTER_RECSYS=twitter`, a wire reporter's post lands in front of agents whose bios match it. With `random`, it might not.

`scheduled_events` will not fire. A second shock later in the day means a second scenario with a different opening post, or a code change in the round loop. Prefer two scenarios. They compare cleanly.

### 7.5 Run

`POST /api/simulation/start`

```json
{
  "simulation_id": "sim_xxxx",
  "platform": "parallel",
  "max_rounds": 24,
  "enable_graph_memory_update": true,
  "force": false
}
```

`force: true` stops a previous run of the same id and deletes action logs. It keeps profiles and `simulation_config.json`.

Poll `GET /api/simulation/<id>/run-status` for progress. For a customer-facing ticker, poll every few seconds and render counts, the current round, and a short page of posts. Do not ship the lab's force-directed graph.

The process stays up after the last round so interviews work. That also means the worker holds the OASIS environment, including MiniLM if Twitter is on, until you close it. Close it when the interviews you need are done: `POST /api/simulation/close-env` with `{ "simulation_id": "sim_xxxx" }`.

### 7.6 Report

`POST /api/report/generate`

```json
{ "simulation_id": "sim_xxxx" }
```

If the response is 409, graph ingestion is still running or the run is not in `completed` or `stopped`. Wait and retry. Do not treat 409 as a failed simulation.

Poll `POST /api/report/generate/status`, then read `GET /api/report/<report_id>/sections`. The report agent can search the Zep graph (`insight_forge`, `panorama_search`, `quick_search`) and interview agents. Those interviews happen inside report generation and are part of why you left the environment open.

`POST /api/report/chat` is the "ask a follow-up" box. Send `simulation_id` and `message`. Persist `chat_history` in your app if the conversation should survive a reload.

### 7.7 Interviews you trigger yourself

`POST /api/simulation/interview` works only while that environment is still in command-wait mode.

```json
{
  "simulation_id": "sim_xxxx",
  "agent_id": 4,
  "platform": "twitter",
  "timeout": 120,
  "prompt": "Which single line in the release changed your view, and what would you need to see next quarter to change it back? If the documents do not say, say you do not know."
}
```

Interview the roles, not the whole cast. Five good interviews are the product. Forty are a bill and a wall of text. Ask for one claim, one condition, and an admission of ignorance. Open prompts ("what do you think?") produce open mush.

`platform` omitted interviews both platforms and returns a `platforms` object. Pin the platform when you want the tape voice rather than the forum voice.

Batch form: `POST /api/simulation/interview/batch` with a list of `{ agent_id, prompt }`. Same liveness rule.

## 8. Scenario design

Each scenario is one question, one packet, one opening post, one clock. Store that as a row in your database, plus the MiroFish `project_id`, `graph_id`, and `simulation_id`.

Three shapes cover most of a finance product. Build them in this order.

**Earnings print.** Packet is this release plus last quarter. Opening post is the wire reporter stating the two numbers that moved. Question is which line becomes the argument. This is the first vertical slice in section 11.

**Policy line.** Packet is the statement plus the previous statement. Cast swaps the company roles for the central bank, bank economists, a rates PM, and a wire. Opening post quotes the sentence that changed. Same pipeline.

**Rumor versus document.** Two scenarios on the same graph. Scenario A opens with the rumor and no filing. Scenario B opens with the filing. The product shows the two narrative reports side by side. Do not blend them into one run. You want the contrast, and `scheduled_events` will not deliver a mid-run filing.

A fourth shape, "what if this executive said X", is an edit of `initial_posts` and a new `simulation_id` created from the same project. Reuse the graph. Call `create` again, `prepare` again, edit the new config, start. Re-preparing costs profile generation. If the cast is unchanged, you can duplicate the simulation directory and only change `initial_posts` and the simulation id, but that is a manual shortcut and it will drift. Prefer prepare.

## 9. Product surfaces

Build four screens. Skip the lab's five-step chrome.

**Scenario.** Company, question, uploaded packet, cast checklist filled from `/entities/.../by-type/...`, round cap, which platform. A disabled Start button until the CFO node and at least one analyst node exist.

**Live run.** Round, simulated hour, posts per role, a stream of new posts from `/posts`. Group by `entity_type`, not by a sentiment color. Sentiment you compute yourself from post text is a label, and small models are bad at it. Show the words.

**Narrative.** The report sections, then the five interviews. Each quote shows the agent name, the type, and the platform. Link the quote to the opening post it is reacting to.

**Compare.** Two saved snapshots. Same graph, different opening post. Diff the claims each role repeated, not a numeric score.

The lab graph is useful while you are debugging ontology. It is the wrong customer view: a finance user wants the CFO's words, not a hairball of edges. Edge-label rendering is also the part of the lab UI that gets expensive. Leave it in the lab.

## 10. How to read a result

After the run, reduce the SQLite posts and the action log yourself. A trustworthy summary uses counts you can recompute:

- How many original posts each entity type wrote, versus reposts and likes.
- Which opening-post claims are repeated, by string or by a later extraction step you own.
- Who followed whom (`FOLLOW` in the action log).
- Whether the short seller and the long-only PM are talking about the same line of the release. If they are not, that is the finding.

Do not collapse this into a price impact. If you show a gauge, label it "share of posts still discussing the guide cut" and make the number a count over a count. Do not label it "expected move".

The report is a synthesis by another LLM with tools. Treat it as a briefing that cites the world, and keep the raw posts one click away. When the briefing and the posts disagree, the posts win.

## 11. First vertical slice

Ship this before any account system or compare view. One operator, one company, one earnings release.

1. Put the production `.env` from section 4 in the MiroFish root. Start the backend on port 5001.
2. Pick a release you already know the real reaction to. You will use that in section 12.
3. Ontology-generate with the requirement from section 6 and two files: this release, last quarter.
4. Reject the ontology if the cast types are missing. Rebuild the requirement, new project.
5. Build the graph. Confirm entities with `/entities/<graph_id>/by-type/SellSideAnalyst` (use whatever type name the ontology actually emitted).
6. Create the simulation with both platforms. Prepare. Read every profile. Rewrite any bio that does not name a constraint (what they hold, what they cover, what they refuse to invent).
7. Edit `time_config` and `initial_posts` as in section 7.4. Set the wire reporter as the poster.
8. Start with `max_rounds: 24` and graph memory on.
9. When status is terminal, generate the report. Interview the CFO, one analyst, the long-only PM, the short seller, and one reporter. Ask the prompt from section 7.7.
10. Close the environment.
11. Save the report sections, the five interviews, and the post list into your app database, keyed by scenario.

The lab UI can do steps 3 through 9 by hand while your app is a script. Automate them only after one run has produced a briefing you would send to someone.

A script shaped like the calls in section 7 is enough. Keep it next to the finance app, not inside `backend/scripts/`, so MiroFish upgrades do not merge-conflict with product code.

## 12. Evaluation

Judge the rehearsal against the public reaction you already saw, on the document you held out of the packet. The news recap can be the grader. It should not also be a seed file, or the agents are parroting the ending.

Score these, in writing, each time you change model, ranker, or cast:

| Check | Pass |
|---|---|
| Facts | Every number in the opening post and in sampled agent posts appears in the uploaded files |
| Roles | A blinded reader can tell the PM note from the wire note from the forum note |
| Focus | The line of the release that dominated real coverage is among the lines the agents argued about |
| Disagreement | At least two roles disagree, for a reason you can point to in their personas |
| Ignorance | Asked about a figure that was not in the packet, the interviewed agent does not invent it |
| Stability | Two runs with the same config do not produce opposite villains. Wording will change. The claim under debate should not. |

Failing "facts" or "ignorance" is a product bug. Fix the prompt and the opening post before you touch temperature or add agents.

Do not score price error. The engine never saw an order.

When a check fails, change one thing. The usual order: persona text, then opening post, then model, then ranker (`twitter` versus `twhin-bert`), then cast size. Adding rounds rarely fixes a bland run. It repeats it.

## 13. Running it as a product

**Worker.** One MiroFish backend per machine, one active simulation per worker. The runner already refuses to start the same `simulation_id` twice. It will happily run two different ids in one process, and on a small box that is how you get the OOM you just removed. Queue scenarios. A worker with the hosted LLM and MiniLM can run one 24-round, dual-platform rehearsal at a time.

**Timeouts.** Localhost gets a 600-second model timeout automatically. A hosted model should stay on the default. An interview `timeout` of 60 seconds is tight for a long quote. Use 120.

**Graph memory.** Turn it on for any run you will report. Turn it off only for a throwaway you will not brief. The report is worse without the simulated posts in Zep, and the 409 wait is the cost of turning it on.

**Snapshots.** Copy the report JSON, the interview responses, and a page of posts into your database at the end. MiroFish will delete action logs on `force: true`. Your product should not depend on `backend/uploads/` surviving.

**Secrets.** `LLM_API_KEY` and `ZEP_API_KEY` stay on the worker. The finance app calls your API, and your API calls MiroFish on a private network. Do not put those keys in the browser.

**Cost.** Profile generation is one LLM call per entity. The run is one call per woken agent per round, per platform. A 30-entity cast, 24 rounds, 10 agents a round, two platforms, is on the order of 500 simulation calls plus 30 profiles plus the report's tool calls. That is the bill to quote. Cutting a platform or the round cap is how you cut it. Cutting the ranker to `random` does not meaningfully cut it, and it does damage the product.

**The 8GB box.** Use it to edit prompts and read posts. Point `LLM_BASE_URL` at the hosted model even there, if the goal is to see real quality. A local 3B model is for checking that the pipeline runs when you have no network, and its briefings are not the ones you evaluate in section 12.

## 14. Compliance

Put this in the product, not only in a terms page.

- The output is a rehearsal of public conversation. It is not investment advice, not a research report under any regulator's definition, and not a prediction of a price.
- Agents are language models wearing personas. A quote is something the model said in character. Label it that way. Do not present it as a statement by the real person whose name was in a filing.
- Do not let a user upload material you are not allowed to process, and do not add a feature whose purpose is to coordinate a story in the real market. The product rehearses reaction to a document the user already has. It does not publish that reaction anywhere.
- Keep the seed files and the generated posts as the audit trail for every briefing you show.

## 15. Build order

1. One scripted earnings scenario through section 11, graded with section 12. No custom UI yet.
2. The scenario and narrative screens, reading MiroFish and saving a snapshot.
3. Compare, as two saved scenarios on one graph.
4. A queue in front of the worker, then auth.
5. Only if section 12 says personas are right and the focus is still wrong: teach the runner to honor `stance` and `influence_weight`, or to fire a second post at a chosen round. That is a MiroFish change. Do it with a test against `backend/scripts/`, and do not do it before you have a scenario that is already factually clean.

The app is top tier when a careful reader trusts the quotes, can see which role said them, and can rerun the same packet with one different opening post. The app is not top tier because the graph animates, or because a gauge says "bullish".
