# GitHub Copilot instructions

This repository is the Hexo source for https://qgu.io/blog. The full agent guide
is `AGENTS.md` at the repo root. Read it before editing.

Critical rules:

- Edit `source/_posts/*.md` only. `main` is the Hexo source; `gh-pages` is
  generated output. Never edit generated HTML.
- Never commit `public/`, `db.json`, or `node_modules/`.
- Never push to `main`. Create a branch (`post/<slug>`) and open a PR.
- Leave a blank line before every Markdown table, otherwise it renders as plain
  text.
- Do not paste diff markers (`+`) into code blocks.
- Front matter requires `title`, `slug`, `date`, `lang`, `category`, `tags`,
  `author`, `summary`.
- Multi-language posts share one `slug`: `<slug>.md` (en), `<slug>-fr.md` (fr),
  `<slug>-cn.md` (中). Add a `> Languages: ...` line after the front matter.
- Validate before a PR: `npm install && node .github/setup-mathjax.js && npm run build`.
