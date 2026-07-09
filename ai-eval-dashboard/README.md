This is the local dashboard for monitoring evaluation runs produced by the
Adaptive Synth Eval CLI.

## Getting Started

Install dependencies with Yarn:

```bash
yarn install
```

Then start the development server:

```bash
yarn dev
```

If you are starting from the repository root:

```bash
cd ai-eval-dashboard
yarn install
yarn dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

The dashboard reads run artifacts from the parent repository, including:

- `../outputs/runs/<run_id>/monitoring_scores.jsonl`
- `../outputs/runs/<run_id>/monitoring_state.json`
- `../outputs/runs/<run_id>/eval_progress.md`

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

Useful Yarn commands:

```bash
yarn dev
yarn build
yarn start
yarn lint
```

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Notes

- The dashboard can trigger local monitoring runs through its server routes, so run it from this repository checkout.
- If `yarn lint` or `yarn build` fails because dependencies are missing, rerun `yarn install` inside `ai-eval-dashboard`.
