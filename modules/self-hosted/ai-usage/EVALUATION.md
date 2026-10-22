# The daily model evaluation procedure

The collector reports what the accounts can do right now. The quality of a
model, and whether it may take a piece of work, is a separate question, and
this procedure is the answer to it. It runs once a day; the quota and the
eligibility reading stay on the five minute timer.

The procedure is one source controlled job. It does not add a service, a
daemon, a database, or a listener. It writes into the state the collector
already keeps.

## What it does

1. **Research the current line of models.** Read the official release notes
   and the benchmark sources of the providers we use, and record what is new:
   the model, the provider, the release date, the source, and the date of
   the read. The record is a fact with a source, never a conclusion.
2. **Pull the Artificial Analysis public pages.** The public pages carry
   the models, their intelligence index, their cost per task and their token
   prices. The pull reads them with ordinary GETs: there is no key, no
   account and no paid feature. The pages are read once a day and never
   more. A page that is blocked, or that answers with a challenge, is
   recorded as blocked and the last good snapshot is kept: nothing is
   retried to get around it. The cache records the intelligence index
   version, the exact model names, the fetch time, and the source, and the
   models the pull found that the one before it did not carry. A model the
   pages do not list is unknown, not bad.
3. **Read the measured admission results.** The free inference pool already
   runs revisioned workload benches and keeps their results in its own
   store. They are read through the broker's read surface
   (`inference_status` with `op=admissions`) and the recorded outcomes become
   the measured evidence of the models. Nothing new is built for this.
4. **Run bounded representative work.** Where an approved route exists, a
   small set of real tasks runs through it: engineering correctness,
   security, integration, and test quality, plus CAD work for the 3D tier.
   The tasks are held out: the task set that judges a model is never the task
   set that was used to build it. Every run records the revision it belongs
   to, the task, the outcome, the latency, the tokens, the cost, and the
   quota it consumed. A model that was never measured is not measured by its
   own implementation: the judging task is separate from the work.
5. **Decide the admission.** A new model is provisional. It is admitted to
   the volume tiers when it has been measured on the held out tasks, and it
   is never promoted for being new, for a high token count, or for a good
   name. The lineage priors stay the labelled fallback for every model
   without a measurement.
6. **Publish.** The cache, the admission evidence, and the new model
   records go into the state the collector reads. The collector then shows
   the measured quality, the coverage, and the version of the feed.

## The rules

- The feed is read through the ordinary credential path. There is no
  challenge, no bypass, no private interface, and no paid plan. The free
  endpoint is the only endpoint that is read.
- The number of requests stays inside the free plan. There is no automatic
  upgrade of any kind.
- A quality score is never invented. A model without a measurement keeps its
  lineage prior, and the prior stays labelled as a prior.
- The frontier review is unchanged: an implementation by a bulk model needs
  a review by the frontier authority, and a required frontier that is
  unavailable is waited for.
- The role cap is independent of the quality: a free route stays in the low
  complexity classes, whatever the measured quality says.
- The collector keeps its own five minute reading of the quota and the
  eligibility. This procedure never touches it.

## How to run it

    python3 modules/self-hosted/ai-usage/evaluate.py --help

The procedure is idempotent: it reads the current state, writes the new
state, and leaves the collector to pick it up on its next run.
