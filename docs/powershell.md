# PowerShell reference (Windows)

## Basic commands
- `Get-ChildItem` / `ls` / `dir` — list files: `ls -Force` (incl. hidden)
- `Get-Content <file>` — read file: `Get-Content README.md` / `cat README.md`
- `Set-Content <file> -Value "text"` — write file
- `Add-Content <file> -Value "text"` — append to file
- `Select-String -Path *.py -Pattern "pattern"` — search text in files (like grep)
- `Get-Command <name>` — find a command
- `Get-Help <cmdlet>` — help: `Get-Help Get-ChildItem -Examples`

## Navigation
- `Set-Location <dir>` / `cd <dir>` — change directory
- `Get-Location` / `pwd` — current directory
- `New-Item -ItemType Directory -Path <dir>` — create directory: `mkdir <dir>`
- `Copy-Item <src> <dst>` / `cp <src> <dst>` — copy
- `Move-Item <src> <dst>` / `mv <src> <dst>` — move
- `Remove-Item <path>` / `rm <path>` — DELETE (dangerous, often blocked)
- `Test-Path <path>` — check existence

## Running code
- `python script.py` — run Python
- `python -m pytest tests/ -v` — run pytest
- `python -m unittest discover` — run unittest
- `node script.js`, `npm test`, `npm run <script>` — Node.js
- `dotnet test` — .NET
- `go test ./...` — Go

## Git
- `git status` — current state
- `git log --oneline -10` — recent commits
- `git diff` — uncommitted changes
- `git diff --stat` — summary of changes

## Piping and output
- `$LASTEXITCODE` — exit code of last native command (0 = success)
- `command | Select-Object -First 20` — limit output
- `command 2>&1 | Out-String` — capture both stdout+stderr as text

## Gotchas
- PowerShell strings use double quotes; `$name` is a variable — escape with backtick
- Paths use backslashes; use `-Path` with quotes if path has spaces
- For writing files always prefer the write_file/edit_file tools over shell
