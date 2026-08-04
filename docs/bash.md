# Bash / Linux reference

## Basic commands
- `ls -la` — list files incl. hidden
- `cat <file>` / `head -n 30 <file>` / `tail -n 30 <file>` — read files
- `grep -rn "pattern" <dir>` — search text recursively
- `find <dir> -name "*.py"` — find files by name
- `wc -l <file>` — count lines
- `pwd` — current directory
- `echo "text"` — print text

## Navigation
- `cd <dir>` — change directory
- `mkdir -p <dir>` — create directory (with parents)
- `cp <src> <dst>` — copy
- `mv <src> <dst>` — move
- `rm -rf <path>` — DELETE (dangerous, usually blocked)
- `test -f <file>` — check file exists

## Running code
- `python3 script.py` — run Python
- `python3 -m pytest tests/ -v` — run pytest
- `python3 -m unittest discover` — run unittest
- `node script.js`, `npm test`, `npm run <script>` — Node.js
- `go test ./...` — Go
- `cargo test` — Rust

## Git
- `git status` — current state
- `git log --oneline -10` — recent commits
- `git diff` — uncommitted changes
- `git diff --stat` — summary of changes

## Piping
- `command | head -n 20` — limit output
- `command 2>&1` — capture stderr
- `echo $?` — exit code of last command (0 = success)

## Gotchas
- Never write files via `>`/`>>` redirects — use write_file/edit_file tools
- Chain commands with `&&` only if both are safe (every segment is checked)
