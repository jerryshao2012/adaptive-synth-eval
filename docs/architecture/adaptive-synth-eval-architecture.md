Let's look at how ASE—Adaptive Synthetic Evaluation—is put together. We've structured this into three layers: control at the top, execution in the middle, and evidence and governance at the bottom.

Starting with control: operators run tests via the CLI. They pass in YAML files to define the rules, keeping config separate from the actual code execution. A guarded loop controller coordinates the runs, enforcing budget limits, policy checks, and a kill switch. If you need to monitor runs or curate golden datasets, you use the Next.js dashboard. For quick, stateless scoring, there's a separate Metrics API that bypasses the dashboard and doesn't write local files.

The middle layer is the runtime. When a contract comes in, we either spin up synth mode to generate simulated user traffic with random failures, or unified mode, which is our main path. Unified mode runs conversations in parallel, mixing normal user behavior with targeted attacks from our Adversarial Response Engine.

That adversarial engine does more than spit out prompts. It picks an attack strategy from a registry, plans the prompt, judges the target's reply, and remembers what worked so it can adapt in later turns. Normal and adversarial paths both talk to the target through a client interface. That keeps the engine isolated from how the target is deployed—whether it's an API, a browser workflow, or a model.

Responses go through a scoring router to flag safety and quality issues. The external LLMs handling generation, planning, and scoring are shown in the clouds on the right. We also separated monitoring from the live path. It reads the chat logs in the background, scores the rows, and saves them. This keeps the live testing loop fast.

The bottom layer handles evidence and governance.

Every run saves its logs, scores, and memory files to a dedicated folder. The dashboard lets humans review this data, and approved logs get promoted to golden datasets for regression testing.

Completed runs also feed our learning coordinator. It runs a champion-challenger process: it inspects evidence, proposes policy tweaks, and tests them in a tournament. It can't touch the target app or model weights, and nothing goes live without human approval. Once approved, the changes are saved in the registry and only loaded at run boundaries to keep tests consistent.

Ultimately, the goal is separation. We test, score, and govern without blurring the boundaries between the target, the monitoring, and human control.