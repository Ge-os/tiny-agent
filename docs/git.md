# Git reference

## Status / inspect
- `git status` — working tree state
- `git log --oneline -10` — last 10 commits
- `git diff` — unstaged changes
- `git diff --staged` — staged changes
- `git diff --stat` — change summary (files, lines)
- `git show <commit>` — show a commit
- `git branch` — local branches

## Staging / committing
- `git add <file>` — stage a file
- `git commit -m "message"` — commit staged changes
- `git commit -am "message"` — stage+commit tracked files

## Branching
- `git checkout -b <branch>` — create + switch
- `git checkout <branch>` — switch
- `git merge <branch>` — merge into current

## Remote
- `git remote -v` — list remotes
- `git fetch` — download remote refs
- `git pull` — fetch + merge
- `git push` — upload commits

## Undo (careful)
- `git restore <file>` — discard unstaged changes to a file
- `git reset <file>` — unstage
- `git stash` — save working changes temporarily
