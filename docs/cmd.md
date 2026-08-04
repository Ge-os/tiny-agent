# CMD Cheat Sheet

## File System Navigation
```cmd
cd                                 # Show current directory
cd <dir>                          # Change directory
cd ..                             # Go up one directory
cd \                              # Go to root of current drive
cd /d D:\                         # Change to different drive and directory
dir                               # List files in current directory
dir /a                            # List all files including hidden
dir /s                            # List files recursively
dir /b                            # Simple listing (names only)
dir /w                            # Wide format listing
dir /o:n                          # Sort by name
dir /o:s                          # Sort by size
dir /od                           # Sort by date (oldest first)
tree                              # Show directory structure
tree /f                           # Show files in directory structure
mkdir <name>                      # Create directory
rmdir <dir>                       # Remove empty directory
rmdir /s <dir>                    # Remove directory and contents
rmdir /s /q <dir>                 # Remove directory quietly (no prompt)
```

## File Operations
```cmd
type <file>                       # Display file contents
more <file>                       # Display file with pagination (press space)
find "text" <file>                # Search for text in file
find /i "text" <file>             # Case-insensitive search
find /v "text" <file>             # Display lines NOT containing text
find /c "text" <file>             # Count lines containing text
copy <source> <dest>              # Copy file
copy /y <source> <dest>           # Copy without confirmation
xcopy <source> <dest> /e          # Copy directories and subdirectories
xcopy <source> <dest> /e /i       # Copy directories, create destination
xcopy <source> <dest> /e /h       # Copy including hidden files
move <source> <dest>              # Move or rename file/directory
del <file>                        # Delete file
del /f <file>                     # Force delete read-only files
del /q <file>                     # Delete without confirmation
erase <file>                      # Delete file (same as del)
ren <old> <new>                   # Rename file
fc <file1> <file2>                # Compare files
comp <file1> <file2>              # Compare files (binary)
attrib +r <file>                  # Make file read-only
attrib -r <file>                  # Remove read-only
attrib +h <file>                  # Hide file
attrib -h <file>                  # Unhide file
attrib +s <file>                  # Make system file
attrib -s <file>                  # Remove system attribute
```

## Redirection & Pipes
```cmd
command > file                    # Redirect stdout to file (overwrite)
command >> file                   # Redirect stdout to file (append)
command 2> file                   # Redirect stderr to file
command 2>&1                      # Redirect stderr to stdout
command < file                    # Use file as stdin
command1 | command2               # Pipe output of command1 to command2
command > nul                     # Suppress output
```

## Process Management
```cmd
tasklist                          # Show running processes
tasklist /v                       # Show detailed process info
tasklist /fi "imagename eq notepad.exe"  # Filter processes
taskkill /pid 1234                # Terminate process by ID
taskkill /im notepad.exe          # Terminate process by name
taskkill /f /im notepad.exe       # Force kill process
start notepad.exe                 # Start program
start /b command                  # Start in background
start /wait command               # Start and wait for completion
```

## System Information
```cmd
systeminfo                        # Show system information
systeminfo | find "OS"            # Find specific system info
ver                               # Show Windows version
hostname                          # Show computer name
whoami                            # Show current username
date                              # Show/Set current date
time                              # Show/Set current time
wmic os get caption               # Get OS name
wmic os get lastbootuptime        # Get system uptime
wmic cpu get name                 # Get CPU information
wmic memorychip get capacity      # Get RAM information
wmic diskdrive get model,size     # Get disk information
wmic logicaldisk get deviceid,size,freespace  # Get disk usage
```

## Network Commands
```cmd
ping google.com                   # Test network connectivity
ping -t google.com                # Continuous ping (Ctrl+C to stop)
ping -n 10 google.com             # Send 10 pings
ping -l 1024 google.com           # Set packet size
tracert google.com                # Trace route to host
tracert -d google.com             # Trace without resolving hostnames
ipconfig                          # Show IP configuration
ipconfig /all                     # Show all IP configuration
ipconfig /release                 # Release IP address
ipconfig /renew                   # Renew IP address
ipconfig /flushdns                # Flush DNS cache
netstat                           # Show network connections
netstat -a                        # Show all connections and ports
netstat -b                        # Show executable for connections
netstat -n                        # Show addresses numerically
netstat -o                        # Show process IDs
netstat -r                        # Show routing table
nslookup google.com               # Query DNS
nslookup 8.8.8.8                  # Reverse DNS lookup
nslookup -type=MX google.com      # Query MX records
nslookup -type=NS google.com      # Query NS records
route print                       # Show routing table
arp -a                            # Show ARP cache
netsh interface show interface    # Show network interfaces
netsh wlan show profiles          # Show saved WiFi profiles
netsh wlan show profile name=SSID key=clear  # Show WiFi password
```

## Command History
```cmd
doskey /history                   # Show command history
F7                                # Show command history in popup
F9                                # Run command by number
Up/Down arrows                    # Navigate history
ESC                               # Clear current line
```

## Environment Variables
```cmd
set                               # Show all environment variables
set VAR=value                     # Set variable
set VAR=                          # Remove variable
echo %VAR%                        # Display variable value
set PATH=%PATH%;C:\New\Path       # Add to PATH temporarily
setx VAR value                    # Set environment variable permanently
setx PATH "%PATH%;C:\New\Path"    # Set PATH permanently
%USERNAME%                        # Current username
%COMPUTERNAME%                    # Computer name
%APPDATA%                         # AppData folder
%PROGRAMFILES%                    # Program Files folder
%WINDIR%                          # Windows directory
%TEMP%                            # Temporary files directory
%CD%                              # Current directory
%DATE%                            # Current date
%TIME%                            # Current time
```

## Batch Scripting Basics
```cmd
@echo off                         # Hide commands
echo message                      # Display message
echo.                             # Display blank line
rem comment                       # Comment line
:: comment                        # Alternative comment (not always supported)
setlocal enabledelayedexpansion   # Enable delayed expansion
pause                             # Pause execution with message
exit /b 0                         # Exit batch with code 0
exit /b 1                         # Exit batch with error code
goto label                        # Jump to label
:label                            # Label for goto
if %var%==value command           # If statement
if exist file command             # Check if file exists
if not exist file command         # Check if file doesn't exist
if errorlevel 1 command           # Check error level
if defined var command            # Check if variable defined
if "%var%"=="value" command       # String comparison
if %var% equ 10 command           # Numeric comparison (equ, neq, lss, leq, gtr, geq)
call script.bat                   # Call another batch file
call :function                    # Call internal function
shift                             # Shift command-line arguments
%0                                # Script name
%1, %2, %3...                     # Script arguments
%*                                # All arguments
%~d0                              # Drive of script
%~p0                              # Path of script
%~n0                              # Name of script
%~x0                              # Extension of script
```

## Loops in Batch
```cmd
for %%i in (list) do command       # For loop
for %%i in (*.txt) do echo %%i     # Process all .txt files
for /f "delims=" %%i in (file.txt) do command  # Read file line by line
for /f "tokens=1,2" %%i in (file.csv) do command  # Parse CSV
for /f "skip=1" %%i in (file.txt) do command  # Skip first line
for /r . %%i in (*.txt) do echo %%i  # Recursive search
for /d %%i in (*) do echo %%i       # Loop through directories
for /l %%i in (1,1,10) do command   # Loop from 1 to 10
for /f "delims=" %%i in ('command') do set var=%%i  # Capture command output
```

## Functions in Batch
```cmd
call :myFunction param1 param2
goto :eof

:myFunction
    echo %1 %2
    exit /b
```

## Error Handling
```cmd
exit /b 0                         # Success
exit /b 1                         # Error
echo %errorlevel%                 # Show last error level
command || echo "Failed"          # Run if command fails
command && echo "Success"         # Run if command succeeds
2>nul                             # Suppress error messages
>nul 2>&1                         # Suppress all output
```

## Text Manipulation
```cmd
find "text" file.txt              # Find text in file
findstr "pattern" file.txt        # Find with regex support
findstr /i "pattern" file.txt     # Case-insensitive
findstr /r "pattern" file.txt     # Use regex
findstr /v "pattern" file.txt     # Exclude matching lines
findstr /n "pattern" file.txt     # Show line numbers
sort file.txt                     # Sort lines
sort /r file.txt                  # Reverse sort
sort /+n file.txt                 # Sort by column n
more file.txt                     # View with pagination
more /e file.txt                  # View with extended commands
type file.txt | more              # Pipe to more
```

## Compression & Archives (Built-in)
```cmd
compact /c file.txt               # Compress file
compact /u file.txt               # Uncompress file
compact /c /s:folder              # Compress folder recursively
compact /u /s:folder              # Uncompress folder recursively
compact /q file.txt               # Query compression status
```

## Disk & File System
```cmd
chkdsk                            # Check disk
chkdsk /f                         # Fix disk errors (requires reboot)
chkdsk /r                         # Find bad sectors and recover info
chkdsk /x                         # Force dismount volume
chkdsk C: /f /r                   # Check C: drive with repair
defrag C:                         # Defragment drive
defrag C: /a                      # Analyze fragmentation
defrag C: /h                      # Defrag with normal priority
vol                               # Show volume label
label C: NewLabel                 # Change volume label
format C: /fs:NTFS                # Format drive
format C: /q                      # Quick format
diskpart                          # Disk partition utility
mountvol                          # Show mounted volumes
fsutil volume list                # Show volumes
fsutil fsinfo drives              # Show available drives
```

## User & Permissions
```cmd
net user                          # Show users
net user username                 # Show user details
net user username password /add   # Add user
net user username /delete         # Delete user
net localgroup                    # Show groups
net localgroup groupname /add     # Add group
net localgroup groupname username /add  # Add user to group
net localgroup administrators username /add  # Make user admin
net share                         # Show shared resources
net share sharename=C:\path /grant:user,FULL  # Create share
net share sharename /delete       # Delete share
cacls file.txt /grant user:F      # Grant full control
cacls file.txt /grant user:R      # Grant read-only
cacls file.txt /remove user       # Remove permissions
cacls file.txt /e /g user:F       # Edit ACL (preserve existing)
icacls file.txt /grant user:F     # Modern alternative to cacls
icacls file.txt /reset            # Reset permissions
takeown /f file.txt               # Take ownership
takeown /f file.txt /r /d y       # Recursive ownership
```

## Service Management
```cmd
net start                         # Show running services
net start servicename             # Start service
net stop servicename              # Stop service
net pause servicename             # Pause service
net continue servicename          # Continue paused service
sc query                          # Show services
sc query servicename              # Show service details
sc start servicename              # Start service
sc stop servicename               # Stop service
sc config servicename start= auto  # Set service to auto-start
sc config servicename start= disabled  # Disable service
sc delete servicename             # Delete service
```

## Scheduled Tasks
```cmd
schtasks                         # Show scheduled tasks
schtasks /create /tn taskname /tr "command" /sc daily /st 09:00  # Create daily task
schtasks /create /tn taskname /tr "command" /sc onlogon  # Run at logon
schtasks /run /tn taskname       # Run task now
schtasks /change /tn taskname /disable  # Disable task
schtasks /change /tn taskname /enable  # Enable task
schtasks /delete /tn taskname /f  # Delete task
```

## Registry Operations
```cmd
reg query HKLM\Software          # Query registry key
reg add HKLM\Software\Key /v Name /t REG_SZ /d Value /f  # Add registry value
reg delete HKLM\Software\Key /v Name /f  # Delete value
reg delete HKLM\Software\Key /f   # Delete key
reg export HKLM\Software\Key backup.reg  # Export key
reg import backup.reg             # Import registry file
reg compare Key1 Key2             # Compare registry keys
reg copy Key1 Key2 /s /f         # Copy registry key recursively
```

## Active Directory (Domain Environment)
```cmd
dsquery user                     # Query users
dsquery computer                 # Query computers
dsquery group                    # Query groups
dsquery ou                       # Query organizational units
dsadd user "CN=John,OU=Users,DC=domain,DC=com" -pwd password  # Add user
dsmod user "DN" -pwd newpassword -mustchpwd yes  # Modify user
dsrm "DN"                        # Remove object
```

## Remote Management
```cmd
mstsc                            # Open Remote Desktop client
mstsc /v:computername            # Connect to remote computer
shutdown /r /t 0                 # Reboot local computer
shutdown /s /t 0                 # Shutdown local computer
shutdown /m \\computer /r /t 0   # Reboot remote computer
shutdown /a                      # Abort shutdown
taskkill /s computer /u user /p password /im process.exe  # Kill remote process
dir \\computer\share             # List network share contents
copy \\computer\share\file .     # Copy from network share
net use Z: \\computer\share      # Map network drive
net use Z: /delete               # Unmap network drive
net use \\computer\share /user:username password  # Connect with credentials
```

## Troubleshooting Commands
```cmd
sfc /scannow                     # Scan system files
sfc /scannow /offbootdir=C:\ /offwindir=C:\Windows  # Offline scan
dism /online /cleanup-image /restorehealth  # Restore system image
dism /online /cleanup-image /scanhealth  # Check system image
chkdsk /f /r                     # Check and repair disk
bootrec /fixmbr                  # Fix MBR
bootrec /fixboot                 # Fix boot sector
bootrec /rebuildbcd              # Rebuild BCD
netstat -ano | findstr :80       # Find process using port 80
tasklist /fi "pid eq 1234"       # Find process by PID
```

## Special Characters & Escape Sequences
```cmd
^                                # Escape character (line continuation)
%VAR%                            # Variable expansion
!VAR!                            # Delayed variable expansion (if enabled)
&                                # Command separator (run multiple commands)
&&                               # Run second command only if first succeeds
||                               # Run second command only if first fails
|                                # Pipe
>                                # Redirect output
>>                               # Append output
<                                # Redirect input
@                                # Suppress echo for command
*                                # Wildcard (any characters)
?                                # Wildcard (single character)
"                                # Quoted string
( )                              # Group commands
;                                # Command separator (same as &)
```

## Common One-Liners
```cmd
# Count files in directory
dir /b | find /c /v ""

# Find files containing text
findstr /s /i "pattern" *.txt

# Kill process by name
taskkill /f /im process.exe

# Monitor log file
type log.txt | find /v ""  # Poor man's tail (not dynamic)

# Show folder size
dir /s /a:-d | find "File(s)"

# Get current date/time for file naming
echo %date:~10,4%%date:~4,2%%date:~7,2%_%time:~0,2%%time:~3,2%%time:~6,2%

# Delete all .tmp files older than 7 days
forfiles /p C:\Temp /s /m *.tmp /d -7 /c "cmd /c del @path"

# Recursively rename files
for /r . %i in (*.txt) do ren "%i" "new_%~nxi"

# Get IP addresses only
ipconfig | findstr /i "ipv4"

# Test multiple servers
ping server1 && ping server2

# Find open ports
netstat -an | find "LISTENING"

# Find large files
forfiles /p C:\ /s /m *.* /c "cmd /c if @fsize GTR 104857600 echo @path @fsize"
```

## Help System
```cmd
command /?                        # Show help for command
help                              # Show list of built-in commands
help command                      # Show help for command
cmd /?                            # Show CMD options
cmd /? | more                     # View help with pagination
echo %errorlevel%                 # Check last error code
```

## Startup & Configuration
```cmd
cmd                               # Open new CMD window
cmd /k command                    # Run command and keep window open
cmd /c command                    # Run command and close window
cmd /t:0a                         # Set background/foreground colors
cmd /a                            # Use ANSI output
cmd /u                            # Use Unicode output
color 0a                          # Change console colors (background=black, text=green)
color /?                          # Show color options
mode con cols=80 lines=40         # Set console size
mode con: cols=120 lines=50       # Set specific size
title "My Window"                 # Set window title
prompt $P$G                       # Set prompt (path and >)
prompt $T$G                       # Set prompt (time and >)
cls                               # Clear screen
```

## Command Aliases (Doskey Macros)
```cmd
doskey /macros                    # List all macros
doskey ll=dir /b                  # Create macro
doskey ls=dir /b
doskey history=doskey /history
doskey clear=cls
doskey /exename=cmd.exe ll=dir /b  # Create macro for CMD only
doskey /macros:all                # Show all macros including from other programs
doskey /reinstall                 # Reinstall doskey
doskey /listsize=50               # Set history size
```

## Event Logs
```cmd
wevtutil qe System /c:10 /rd:true /f:text  # Show last 10 system events
wevtutil qe Application /c:5 /rd:true /f:text  # Show last 5 app events
wevtutil qe Security /c:5 /rd:true /f:text  # Show last 5 security events
wevtutil el                        # List all event logs
wevtutil gl System                 # Get log info
wevtutil cl System                 # Clear system log
```

## PowerShell Integration
```cmd
powershell -Command "Get-Process"  # Run PowerShell command
powershell -File script.ps1        # Run PowerShell script
powershell -ExecutionPolicy Bypass -File script.ps1  # Bypass execution policy
powershell -NoProfile -Command "command"  # Run without loading profile
powershell -Command "& {commands}"  # Run multiple commands
```

## Environment & PATH Management
```cmd
path                              # Show PATH
path %PATH%;C:\New\Path           # Add to PATH temporarily
setx PATH "%PATH%;C:\New\Path" /m  # Set PATH system-wide (requires admin)
setx PATH "%PATH%;C:\New\Path"    # Set PATH for current user
where command                     # Find location of command
where /r C:\ file.txt             # Find file recursively
where /q command                  # Quiet mode (just set errorlevel)
```

## File Attributes & Properties
```cmd
attrib                           # Show attributes
attrib +r file                   # Read-only
attrib -r file                   # Remove read-only
attrib +h file                   # Hidden
attrib -h file                   # Unhide
attrib +s file                   # System
attrib -s file                   # Remove system
attrib +a file                   # Archive
attrib -a file                   # Remove archive
dir /a:r                         # List read-only files
dir /a:h                         # List hidden files
dir /a:s                         # List system files
dir /a:a                         # List archive files
dir /a:-d                        # List files only (no directories)
dir /a:d                         # List directories only
```

## File Types & Associations
```cmd
assoc                            # List file associations
assoc .txt                       # Show association for .txt
assoc .txt=txtfile               # Set association
ftype txtfile                    # Show command for file type
ftype txtfile=C:\Program Files\Notepad++\notepad++.exe "%1"  # Change default program
ftype txtfile=type "%1"          # Use type command
```

## Print Management
```cmd
print file.txt                   # Print file
net print                        # Show print jobs
net print \\computer\printer     # Show jobs on remote printer
net print \\computer\printer /delete  # Delete all jobs
rundll32 printui.dll,PrintUIEntry /?  # Print UI options
```

## Terminal & Console Control
```cmd
chcp                             # Show code page
chcp 65001                       # Set UTF-8 code page
chcp 437                         # Set US code page
title "New Title"                # Change window title
color 0a                         # Change colors (0=black, a=green)
color /?                         # Show color options
mode con cols=120 lines=50       # Set console size
mode con: rate=31 delay=1        # Set keyboard repeat rate
```