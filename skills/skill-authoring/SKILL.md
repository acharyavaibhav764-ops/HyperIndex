---
name: skill-authoring
description: Use when creating, formatting, or registering a new Skill in /skills/. Defines the SKILL.md standard, the /skills/ storage layout, and the skills_index.json registration procedure.
category: meta
---

# Skill Authoring

Procedural memory for myself. A Skill is a Markdown file that encodes a recurring,
complex workflow so it does not have to be re-derived each session.

## The Standard (SKILL.md)

Every skill MUST be a Markdown file with a YAML frontmatter block followed by
exactly three sections: `Workflow`, `Pitfalls`, `Verification`.

```markdown
---
name: skill-name
description: Use when <trigger>. <one-line behavior>.
category: optional-category
---

# Skill Name

<one paragraph: what this workflow accomplishes and when it matters.>

## Workflow

1. <Step one — a concrete, ordered action.>
2. <Step two.>
...

## Pitfalls

- **<Failure mode>.** <How to avoid it.>

## Verification

- [ ] <Checklist item that proves the task completed correctly.>
```

### Frontmatter rules

| Field         | Required | Value                                                                 |
| ------------- | -------- | --------------------------------------------------------------------- |
| `name`        | yes      | lowercase, `[a-z0-9-]`, matches the containing directory name exactly   |
| `description` | yes      | MUST start with `Use when <trigger>.` then one line of behavior       |
| `category`    | no       | free-form grouping label (e.g. `meta`, `build`, `review`, `data`)     |

The `description` is the entire discovery surface: it is read from
`skills_index.json` without opening the file. It must therefore state *when*
the skill fires, not just what it does.

### Section rules

- **Workflow** — imperative, numbered, ordered steps. A step is one action a
  machine or agent can execute without asking a follow-up question. Include
  exact commands, file paths, and schemas. This section is the runbook.
- **Pitfalls** — failure modes observed in practice, each with the avoidance
  rule. Not generic advice; only things that actually go wrong.
- **Verification** — a checklist of observable checks. A step is not finished
  until its verification item passes.

## The Storage

All skills live under `/skills/`, one directory per skill:

```
/skills/
  skills_index.json          <- registration table
  skill-authoring/
    SKILL.md
  <other-skill>/
    SKILL.md
```

Layout rules:

- One skill per directory. The directory name MUST equal the frontmatter
  `name` field.
- The file inside MUST be named exactly `SKILL.md` (uppercase).
- No files other than `SKILL.md` in a skill directory, unless the workflow
  genuinely requires helper scripts or references, in which case name them
  descriptively and reference them by relative path from the skill directory.
- `/skills/` is the only sanctioned location. Never write a skill into a
  project source tree, `node_modules`, or a build output directory.

## The Registration Logic

Registration means one entry in `/skills/skills_index.json`.

```json
{
  "skills": [
    {
      "name": "skill-authoring",
      "description": "Use when creating, formatting, or registering a new Skill in /skills/. Defines the SKILL.md standard, the /skills/ storage layout, and the skills_index.json registration procedure.",
      "category": "meta",
      "path": "skill-authoring/SKILL.md"
    }
  ]
}
```

Top-level shape:

- `skills` — array of skill objects. Order is registration order; append only.
- `updated` — ISO-8601 timestamp of the last registration change.

Per-skill object:

- `name` — MUST match the frontmatter `name` and the directory name.
- `description` — MUST match the frontmatter `description` byte-for-byte.
- `category` — mirrors frontmatter `category`, or omitted if frontmatter omits it.
- `path` — forward-slash relative path from `/skills/`, always ends in `SKILL.md`.

### Discovery flow (run this at session start, and before any non-trivial task)

1. Read `/skills/skills_index.json`.
2. If the file is missing, do not guess — report that no skills are registered
   and proceed without them.
3. Compare each `description` against the current goal.
4. On a match, read that skill's `path` and follow it **strictly**.
5. Multiple matches: load all of them, most specific first.

## Creating a New Skill

1. Confirm the workflow recurs and is complex enough to be worth encoding. A
   one-off is not a skill.
2. `mkdir /skills/<name>`.
3. Write `/skills/<name>/SKILL.md` from the template above.
4. Append the entry to `/skills/skills_index.json`, with `description` copied
   verbatim from the frontmatter.
5. Bump `updated` to the current ISO-8601 timestamp.
6. Validate (see Verification).

## Pitfalls

- **Description drift.** A frontmatter `description` edited after registration
  makes the index stale; the skill then never matches. Copy it verbatim, and
  when editing an existing skill, update the index in the same commit.
- **Weak triggers.** `description: Handles parsing.` is undiscoverable —
  nothing about *when* to load it. Always lead with `Use when <trigger>.`
- **Directory/file name mismatch.** `skills/pdf-tools/SKILL.md` with
  `name: pdf_tools` breaks lookup. All three names must agree: directory,
  frontmatter `name`, index `name`.
- **Vague Workflow steps.** "Handle errors appropriately" is not executable.
  Name the command, the path, the exact fallback.
- **Skipping registration.** A `SKILL.md` with no index entry is invisible. Write
  the file and the index entry in the same operation.
- **Non-append index edits.** Reordering or rewriting the `skills` array loses
  the registration history. Append, and never reorder existing entries.
- **SKILL.md outside /skills/.** A skill in a project tree will be deleted by a
  clean, lost to a branch switch, or committed by accident.
- **Over-scoping a skill.** One skill per workflow. Bundling unrelated
  procedures means a single loaded skill carries irrelevant instructions and
  dilutes compliance.

## Verification

- [ ] `/skills/skills_index.json` exists, is valid JSON, and parses.
- [ ] Every `skills[].name` has a matching directory and a `SKILL.md` inside it.
- [ ] Every `skills[].path` resolves to a file that exists on disk.
- [ ] Every `skills[].description` matches its `SKILL.md` frontmatter
      `description` exactly.
- [ ] Every `SKILL.md` has a closed YAML frontmatter block with `name` and
      `description`, and all three sections `Workflow`, `Pitfalls`, `Verification`.
- [ ] Frontmatter `name` == directory name == index `name` (case-sensitive).
- [ ] Node IDs / identifiers in the skill (if any) are unique.
- [ ] `updated` reflects the last change.
