---
title: "Manage Monorepo Dependencies with AI"
slug: manage-monorepo-dependencies
description: "Keep dependency versions in sync across monorepo packages and resolve version conflicts automatically."
skills: [monorepo-manager, code-reviewer, security-audit]
category: development
tags: [monorepo, dependencies, workspaces, turborepo, developer-productivity]
---

# Manage Monorepo Dependencies with AI

## The Problem

Your monorepo has 20 packages and 4 apps. React is on three different versions across different workspaces. TypeScript configs are subtly different -- one package uses `strict: true`, another uses `strictNullChecks: false`, and a third has a tsconfig that hasn't been updated since the monorepo was 3 packages. A junior developer adds `lodash` directly to an app instead of the shared utils package, creating the fourth copy in the dependency tree.

Nobody knows which packages depend on which. Builds randomly fail with type errors that disappear when you delete `node_modules` and reinstall -- the classic "have you tried turning it off and on again" of monorepo development. "It works on my machine" is the team motto because different developers have different versions of pnpm, which resolves the dependency tree differently. Last week, a PR that changed nothing in the UI library caused a type error in the web app because TypeScript 5.2 in one package infers differently from TypeScript 5.4 in another.

Dependency chaos costs hours per week in debugging phantom type errors, version conflicts, and mysterious CI failures that can't be reproduced locally. The team has gotten so used to flaky builds that they've developed a habit of just re-running CI -- but the failures aren't random. They're deterministic consequences of version mismatches that nobody has mapped out.

## The Solution

Using the **monorepo-manager** skill to audit, sync, and maintain dependencies across all workspaces, combined with **security-audit** to catch vulnerable transitive dependencies and **code-reviewer** to review dependency changes before merging, the agent maps the entire dependency graph, identifies every mismatch, and fixes them in the right order.

## Step-by-Step Walkthrough

### Step 1: Map the Monorepo Structure

```text
Analyze our monorepo structure. Show me all packages, their internal
dependencies, and the tooling we're using.
```

The workspace scan reveals the full picture: 14 packages across `apps/` and `packages/`, using pnpm workspaces with Turborepo for build orchestration. Total external dependency count: 347 packages in the lock file, with 89 unique top-level dependencies across all workspaces. The internal dependency graph is clean -- no circular dependencies:

```
packages/types       -> (no deps)
packages/utils       -> types
packages/ui          -> types, utils
packages/database    -> types
apps/web             -> ui, utils, database, types
apps/api             -> database, utils, types
apps/admin           -> ui, utils, types
```

This graph matters because it determines the order in which dependency changes need to propagate. Updating TypeScript in `packages/types` means every downstream package needs to be verified. It also reveals that `packages/types` is the foundation -- a breaking change there ripples through everything.

The agent also flags structural issues: `apps/web` imports from 4 internal packages (reasonable), but `lodash` appears in 4 separate package.json files instead of being provided once through `packages/utils`. That's 4 copies in the `node_modules` tree, 4 places to update, and 4 chances for version drift.

### Step 2: Audit Dependency Versions

```text
Find all dependency version mismatches across our packages. Show the worst offenders.
```

Seven mismatches across the monorepo, two of which are major version splits:

| Dependency | Versions in Use | Packages Affected | Risk |
|-----------|----------------|-------------------|------|
| react | 18.3.1, 18.2.0 | 3 | Low -- minor version |
| typescript | 5.4.2, 5.3.3, 5.2.2 | 8 | High -- type inference differences |
| zod | 3.22.4, 3.21.1 | 4 | Low -- minor version |
| @types/node | 20.11.5, 20.10.0, 20.9.0 | 6 | Low -- type definitions |
| eslint | 9.0.0, 8.57.0 | 5 | High -- major version split |
| vitest | 1.3.1, 1.2.0 | 4 | Low -- minor version |
| date-fns | 3.3.1, 2.30.0 | 2 | High -- major version split, API changes |

The TypeScript mismatch is the most insidious. Version 5.2 and 5.4 have different type inference behavior, which means the shared UI library can produce different type errors depending on which version of TypeScript the consuming package uses. This is the root cause of the "works on my machine" problem -- it literally compiles differently on different packages.

### Step 3: Fix Mismatches with a Plan

```text
Sync all dependencies to their latest compatible versions. Show me what will
change before applying.
```

The agent produces a migration plan organized by risk level:

**Low risk (minor bumps, apply first):**
- react 18.2.0 -> 18.3.1 across 3 packages
- zod 3.21.1 -> 3.22.4 across 4 packages
- vitest 1.2.0 -> 1.3.1 across 4 packages
- @types/node unified to 20.11.5 across 6 packages

**High risk (major version splits, apply with care):**
- eslint 8.57.0 -> 9.0.0 -- requires migrating config from `.eslintrc` to the new flat `eslint.config.js` format across 5 packages
- date-fns 2.30.0 -> 3.3.1 -- import structure changes from `import { format } from 'date-fns'` to individual function imports, affects 2 packages

Each high-risk upgrade includes a list of breaking changes and the specific files that need modification. The eslint migration is the most labor-intensive because every package has its own config file, but the new flat config format is actually simpler -- a good time to consolidate.

After review, the agent updates all package.json files in dependency order (leaf packages first, apps last) and runs `pnpm install && pnpm turbo build` to verify everything compiles. The build cache invalidates for all packages on the first run, but subsequent builds benefit from consistent versions across the graph.

### Step 4: Check for Security Issues

```text
Now run a security audit on our updated dependencies.
```

With versions unified, the security scan is more meaningful -- no more duplicate advisories for the same vulnerability in different versions of the same package. The agent runs `pnpm audit` against the full dependency tree and cross-references with the GitHub Advisory Database.

In this case it finds 3 advisories:

- **High severity:** ReDoS vulnerability in an older `semver` version pulled as a transitive dependency by eslint 8. The eslint 9 upgrade from Step 3 already resolved this by dropping the vulnerable dependency entirely.
- **Moderate severity:** Prototype pollution in a transitive dependency of `lodash`. Resolved by deduplicating lodash to a single copy in `packages/utils` and pinning to the patched version.
- **Low severity:** Information disclosure in a test utility. No production impact (dev dependency only), but updated anyway for a clean audit report.

The unified versions mean the audit produces a clean, deduplicated list instead of the same advisory repeated 4 times for 4 different lodash installations.

### Step 5: Set Up Ongoing Enforcement

```text
How do I prevent version drift from happening again?
```

Four mechanisms prevent the monorepo from drifting back to chaos:

- **pnpm `catalog:` protocol** -- pin shared dependency versions in a single `pnpm-workspace.yaml` catalog, so packages reference `catalog:react` instead of a hardcoded version number. Change the version in one place, every package gets it.

- **CI check** -- a pipeline step runs `syncpack list-mismatches` and fails the build if any package uses a version that doesn't match the catalog. This is the enforcement mechanism -- a developer can't accidentally introduce a new version mismatch without CI catching it before merge.

- **Renovate or Dependabot** -- automated PRs for dependency updates, configured to update the catalog entry so all packages move together. One PR bumps React across the entire monorepo instead of separate PRs for each package.

- **syncpack config** -- a `.syncpackrc.json` that enforces version policies and catches drift in pre-commit hooks, so developers get feedback before they even push.

Together these four mechanisms form a closed loop: the catalog defines truth, CI enforces it, automation keeps it current, and pre-commit hooks catch mistakes early. The result is that dependency management becomes a non-issue -- the system handles it automatically, and developers only think about it when Renovate opens a PR with a version bump.

The agent also recommends consolidating the 4 duplicate `lodash` installations into a single export from `packages/utils`. Instead of each app importing `lodash` directly, they import utility functions from the shared package. This eliminates 3 copies from the dependency tree and ensures all apps use the same lodash version and the same set of functions -- reducing the bundle size across all three apps.

## Real-World Example

Priya leads a frontend platform team at a 30-person B2B startup. Their monorepo grew from 3 packages to 22 over two years. Different teams added dependencies independently, and nobody owned the dependency graph.

She asks the agent to audit the monorepo and finds 14 version mismatches, including three major version splits. The most damaging: TypeScript 5.2 versus 5.4 across different packages, causing type inference differences that break the shared UI library intermittently -- the exact problem that's been causing the "flaky" CI builds.

She asks the agent to sync TypeScript to 5.4.2 everywhere. It updates 8 package.json files in the correct dependency order (leaf packages first, apps last), runs `pnpm install && pnpm turbo build`, and confirms all packages compile cleanly. The eslint 8 to 9 migration takes longer because it requires converting config files, but the agent handles that too -- consolidating 5 separate `.eslintrc` files into 2 shared `eslint.config.js` files that the workspaces extend.

Total time: 20 minutes. The previous manual attempt took a full sprint day and broke staging because the engineer updated packages in the wrong order -- apps before their dependency packages -- causing type mismatches that cascaded through the build.

Build times improve as a side effect: Turborepo caches more effectively when packages share consistent dependency versions, because fewer cache keys change between builds. The CI pipeline that took 14 minutes now completes in 9 minutes -- a 36% improvement from nothing more than version consistency.

The syncpack CI check proves its value the following week when a new developer adds `zod@3.21.1` to a package. The build fails immediately with a clear message: "Version mismatch: zod should be 3.22.4 (catalog) but found 3.21.1 in apps/admin." Five minutes to fix instead of days of mysterious type errors. The team's reaction: "Why didn't we set this up two years ago?"

The real payoff is cultural. Dependency management stops being a source of friction and becomes a solved problem. Engineers add dependencies to the catalog, CI enforces consistency, and Renovate handles updates. Nobody debugs version conflicts anymore.
