# job-radar

Emails you when a new internship is posted that fits your profile (AI/ML,
robotics/RL, and SWE roles at AI startups), within minutes of it appearing on
the company's own job board.

## Setup (about 10 minutes)

1. Create a **public** GitHub repo and push this folder to it. Public matters:
   Actions minutes are free and unlimited for public repos, while a private
   repo's 2,000 free minutes per month cannot cover a run every 5 minutes. The
   repo holds no secrets, only the watchlist and the ids of jobs already seen.
   If you want it private, change the cron in `.github/workflows/poll.yml` to
   `*/20 * * * *`.
2. Make a sending mailbox. Easiest: a personal Gmail with 2-step verification
   on, then create an app password (Google Account > Security > App passwords).
   University accounts often block app passwords, so send *from* a personal
   Gmail *to* whichever address you read.
3. In the repo: Settings > Secrets and variables > Actions > New repository secret:
   - `SMTP_USERNAME`: the Gmail address
   - `SMTP_PASSWORD`: the app password
   - `EMAIL_TO`: where alerts should land
   (For a non-Gmail provider, also set repository *variables* `SMTP_HOST` and `SMTP_PORT`.)
4. Actions tab > enable workflows > run **test-email** to confirm delivery.
5. Run **discover** once (finds job boards for the hand-listed and YC companies),
   then run **poll** once. The first poll sends a single "radar is live" email
   with the best currently-open matches and records everything open today as
   already seen. After that you only hear about new postings.

## How it works

| Workflow | When | What |
|---|---|---|
| `poll` | every 5 min | Fetches every board on the watchlist plus the trackers, emails new strong matches immediately, queues weaker ones |
| `digest` | daily, ~7:23am PT | Emails the queue |
| `discover` | Mondays | Adds newly found boards, refreshes the AI/startup company directory, un-pauses failing boards |

Sources, fastest first:

- **Company job boards** on Greenhouse, Lever and Ashby, read through their
  public JSON endpoints. This is the speed advantage: a posting shows up here
  the moment the company publishes it. `data/boards.json` is the watchlist.
- **Hacker News job stories** (YC startups announcing roles).
- **Community trackers** (SimplifyJobs, vanshb03). Slower, but they cover
  companies on Workday or custom career sites that are not polled directly.

Not covered, on purpose: LinkedIn and Instagram (scraping both breaks their
terms and gets accounts restricted), and Work at a Startup (login required).
Set LinkedIn's own job alerts and a Work at a Startup saved search alongside this.

## Tuning

Everything about matching lives in `config/profile.toml`:

- `instant_threshold` / `digest_threshold`: raise them if email volume is too high.
- `role_groups`: title keywords and the points each group is worth.
- `company_bonus`: extra points for AI companies and for startups.
- `exclude`: titles, degree levels and locations to drop.

`config/extra_companies.txt` is the hand-kept list of AI/robotics companies
outside YC. Add a name there and the next `discover` run looks for its board.
To add a board directly, append `{"ats": "ashby", "slug": "...", "company_name": "...", "discovered_via": "manual"}`
to `data/boards.json` (the slug is the part after `jobs.ashbyhq.com/`,
`job-boards.greenhouse.io/` or `jobs.lever.co/` in the company's job links).

## Layout

```
config/profile.toml          matching rules
config/extra_companies.txt   hand-listed AI/robotics companies
data/boards.json             watchlist of ATS boards (machine-maintained)
data/company_directory.json  which companies count as AI / startup (machine-maintained)
state/state.json             seen jobs + digest queue (written by the workflows)
jobradar/sources/            one module per source
jobradar/scoring.py          internship filter and fit score
jobradar/discovery.py        watchlist growth
jobradar/cli.py              poll / digest / discover / test-email
tests/                       python3 -m unittest discover -s tests
```

Run locally without sending anything:

```
python3 -m jobradar poll --dry-run --state-path /tmp/radar-state.json
```

No dependencies beyond Python 3.11+.

## Things to know

- GitHub's scheduler is best-effort: "every 5 minutes" is typically every 5 to 15.
- A board that fails 12 polls in a row is paused until the next `discover` run.
- Boards found by guessing a slug (`"discovered_via": "probe"`) can occasionally
  belong to a different company with the same name. Delete the entry if you spot one.
- If sending an email fails, the run fails without saving state, so the next
  run retries the same jobs; GitHub also notifies you about the failed run.
