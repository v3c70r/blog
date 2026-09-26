# AGENTS.md

This repository is the Hexo source for the personal blog at https://qgu.io/blog.
It is written for both humans and AI coding agents. If you are an agent asked to
"write a post", "add a blog entry", "translate this post", or "publish
something", read this file first.

## What this repo is

- Branch `main` is the Hexo source. This is the branch you edit.
- Branch `gh-pages` is the generated site. Never edit it by hand.
- `.github/workflows/deploy.yml` builds `main` with Hexo and publishes the
  result to `gh-pages` on every push to `main`.
- `public/`, `db.json`, and `node_modules/` are generated or installed. They are
  gitignored. Never commit them.

## Golden rules

1. Never commit `public/`, `db.json`, or `node_modules/`.
2. Never push to `main` directly. Work on a branch and open a PR.
3. Never edit `gh-pages` or the generated HTML.
4. Keep every language version of a post in sync: same `slug`, same numbers,
   same structure.
5. Do not paste diff markers (`+`, `-`) into code blocks.
6. Leave a blank line before every Markdown table, or it will not render.
7. Run the local build before opening a PR.

## Repo layout

```
_config.yml                    Hexo config (theme: next, permalink, i18n_dir: :lang)
package.json                   Hexo + Next theme dependencies
source/_posts/                 all posts live here
source/_data/head.swig         theme head injection
.github/workflows/deploy.yml   build + deploy on push to main
.github/setup-mathjax.js       theme tweak, must run before building
```

## Add a post

### 1. Front matter

Every post is a Markdown file in `source/_posts/` that starts with:

```yaml
---
title: A short, descriptive title
slug: some-slug
date: 2026-09-22 12:00
lang: en
category: llm
tags: llama.cpp, ROCm, R9700
author: Qing Gu
summary: One sentence used for search and previews.
---
```

- `slug` is shared by all language versions of the post. The permalink is
  `:year/:month/:day/:title/`, where `:title` is the filename slug.
- `date` uses `YYYY-MM-DD HH:mm` and determines the URL. Pick a real date.
- `category` is a single value. `tags` is a comma-separated list.
- `summary` is required. Keep it to one sentence.

### 2. Body

- Plain GitHub-flavored Markdown. `marked` renders it with GFM enabled.
- Use `##` / `###` headings, fenced code blocks with a language tag, and tables.
- Tone for this blog: first person, technical, direct. Say what was measured and
  what was not. Do not invent numbers or benchmarks.
- Keep commands and code plain ASCII. Avoid em dashes and other exotic Unicode
  inside code blocks.

### 3. Multi-language posts

Each language is its own file. Filenames and the `lang` value:

| language           | file           | lang |
|--------------------|----------------|------|
| English            | `<slug>.md`    | `en` |
| French             | `<slug>-fr.md` | `fr` |
| Simplified Chinese | `<slug>-cn.md` | `中` |

All versions share the same `slug`. Add a language switcher line right after the
front matter so readers can jump between them:

```markdown
> Languages: [English](/blog/YYYY/MM/DD/<slug>/) | [Français](/blog/YYYY/MM/DD/<slug>-fr/) | [中文](/blog/YYYY/MM/DD/<slug>-cn/)
```

Use the `date` from the front matter for `YYYY/MM/DD` and the filename slug.
Write `Français` with the cedilla. When you add or edit a post, update every
language version in the same PR, unless the author asked for a single language.

## Validate before opening a PR

```sh
npm install
node .github/setup-mathjax.js
npm run build
```

`setup-mathjax.js` must run before `npm run build`. It patches the theme config
and removes `hexo-math`.

Then check the output for each language:

```sh
# every language generated a page
ls public/YYYY/MM/DD/<slug>*/index.html

# tables actually rendered (expect a non-zero count)
grep -c '<table>' public/YYYY/MM/DD/<slug>/index.html

# no raw pipe tables leaked into the page text
grep -c '| Layer |' public/YYYY/MM/DD/<slug>/index.html
```

If output looks stale, run `npx hexo clean` and rebuild.

## Common pitfalls

- **Tables render as plain text.** GFM needs a blank line between the lead-in
  sentence and the table header row. This is the most common mistake by far.
- **Stray diff markers.** Copying code out of a diff can leave a leading `+`
  inside a fenced block, which breaks copy-paste for readers. Check with
  `grep -nE '^\+' source/_posts/*.md`.
- **Hexo build cache.** Hexo uses `db.json`. If a change seems ignored, run
  `npx hexo clean` and build again.
- **`package-lock.json` churn.** `npm install` can rewrite the lockfile. Do not
  commit that churn unless you actually changed dependencies.
- **Generated files.** `public/` and `db.json` are gitignored, but run
  `git status` before committing anyway.

## Git and PR workflow

```sh
git checkout main
git pull
git checkout -b post/<slug>
# edit source/_posts/*
git add source/_posts/<slug>.md source/_posts/<slug>-fr.md source/_posts/<slug>-cn.md
git commit -m "Add post: <title>"
git push -u origin post/<slug>
gh pr create --repo v3c70r/blog --base main --head post/<slug>
```

- Branch naming: `post/<slug>` for new posts, otherwise a short descriptive name.
- Open the PR. Do not merge it. Merging is a human decision and it triggers the
  public deploy.
- Do not post comments or reviews on a PR on the author's behalf unless you are
  explicitly asked to.

## Note

This is the only agent guide in the repo. Most harnesses read `AGENTS.md`
directly. If you use one that only looks for a fixed filename (for example
Claude Code's `CLAUDE.md` or Gemini CLI's `GEMINI.md`), symlink that filename to
this file instead of duplicating the content.
