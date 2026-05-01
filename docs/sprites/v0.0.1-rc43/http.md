# Sprites API v1 — HTTP examples

Sprite environment: **v0.0.1-rc43**. Source: PDFs in `http/`.

## Contents

- [Overview](#overview)
- [Management](#management)
- [Exec](#exec)
- [Services](#services)
- [File System](#file-system)
- [Checkpoints](#checkpoints)
- [Port Proxy](#port-proxy)
- [Network](#network)

## Overview

QUICK START
0
Install
export SPRITES_TOKEN=acme/1ef8/...
1
Create a sprite
curl -X POST "https://api.sprites.dev/v1/sprites" \
 -H "Authorization: Bearer $SPRITES_TOKEN" \
 -H "Content-Type: application/json" \
 -d '{"name":"my-sprite"}'
2
Run Python
echo 'print(2+2)' | curl -X POST "https://api.sprites.dev/v1/sprites/my-s
 -H "Authorization: Bearer $SPRITES_TOKEN" \
 --data-binary @-
3
Clean up
curl -X DELETE "https://api.sprites.dev/v1/sprites/my-sprite" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
ORCHESTRATION
Sprites
Provision and manage isolated Linux sandboxes with persistent filesystems.
POST Create sprite
GET List sprites
GET Get sprite
PUT Update sprite
DELETE Delete sprite
COMMANDS

Exec
Execute commands inside sprites via WebSocket. Stream stdin/stdout and manage processes.
WSS Start command
GET List sessions
WSS Attach to session
Services
Manage persistent background services running in sprites.
Filesystem
Read, write, and manage files within sprites.
STORAGE
Checkpoints
Create point-in-time snapshots and restore to previous states.
POST Create checkpoint
GET List checkpoints
GET Get checkpoint
POST Restore checkpoint
NETWORKING
Proxy
Tunnel TCP connections to ports inside sprites.
WSS Connect to port
Network Policy
Control outbound network access with DNS-based filtering rules.
GET Get policy
POST Update policy

## Management

Sprite Management
Sprites are persistent environments that hibernate when idle and wake automatically on
demand. You only pay for compute while actively using them—storage persists indefinitely.
Create Sprites for development environments, CI runners, code execution sandboxes, or any
workload that benefits from fast startup with preserved state. Each Sprite gets a unique URL
for HTTP access, configurable as public or authenticated.
Create Sprite

### `POST /v1/sprites`

Create a new sprite with a unique name in your organization

**REQUEST BODY**

application/json
name* string
Unique name for the sprite within the organization
url_settings
URL access configuration
auth "sprite" | "public"
Authentication type (default: sprite)

**RESPONSE**

application/json
id* string
Unique sprite identifier (UUID)
name* string
Sprite name within the organization
organization* string

Organization slug
url* string
Sprite HTTP endpoint URL
url_settings
URL access configuration
auth* "sprite" | "public"
Authentication type
status* "cold" | "warm" | "running"
Runtime status
created_at* string
Creation timestamp (ISO 8601)
updated_at* string
Last update timestamp (ISO 8601)
last_started_at string
When the sprite machine last started (ISO 8601), null if not tracked
last_active_at string
When the sprite was last active/running (ISO 8601), null if not tracked

**RESPONSE CODES**

201
Created
400
Invalid request parameters
401
Missing or invalid authentication

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites" \
 -H "Authorization: Bearer $SPRITES_TOKEN" \
 -H "Content-Type: application/json" \
 -d '{"name":"my-sprite","url_settings":{"auth":"public"}}'
```

**200 Response**


{
 "id": "01234567-89ab-cdef-0123-456789abcdef",
 "name": "my-dev-sprite",
 "status": "cold",
 "url": "https://name-random-alphanumeric.sprites.app",
 "url_settings": {
   "auth": "sprite"
 },
 "created_at": "2024-01-15T10:30:00Z",
 "organization": "my-org",
 "updated_at": "2024-01-15T14:22:00Z",
 "last_active_at": "2024-01-15T14:22:00Z",
 "last_started_at": "2024-01-15T14:20:00Z"
}
List Sprites

### `GET /v1/sprites`

List all sprites for the authenticated organization

**QUERY PARAMETERS**

prefix string
Filter sprites by name prefix
max_results number
Maximum number of results (1-50, default: 50)
continuation_token string
Token from previous response for pagination

**RESPONSE**

application/json
sprites* SpriteEntry[]

List of sprite entries
name* string
Sprite name
org_slug* string
Organization slug
updated_at string
Last update timestamp (ISO 8601)
has_more* boolean
Whether more results are available
next_continuation_token string
Token for fetching the next page of results

**RESPONSE CODES**

**200 Success**

401
Missing or invalid authentication

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
{
 "sprites": [
   {
     "name": "my-dev-sprite",
     "org_slug": "my-org",
     "updated_at": "2024-01-15T14:22:00Z"
   }
 ],
 "next_continuation_token": "eyJsYXN0IjoibXktZGV2LXNwcml0ZSJ9",
 "has_more": true
}
```


Get Sprite

### `GET /v1/sprites/{name}`

Get details for a specific sprite

**PATH PARAMETERS**

name* string
Unique sprite name

**RESPONSE**

application/json
id* string
Unique sprite identifier (UUID)
name* string
Sprite name within the organization
organization* string
Organization slug
url* string
Sprite HTTP endpoint URL
url_settings
URL access configuration
auth* "sprite" | "public"
Authentication type
status* "cold" | "warm" | "running"
Runtime status
created_at* string
Creation timestamp (ISO 8601)

updated_at* string
Last update timestamp (ISO 8601)
last_started_at string
When the sprite machine last started (ISO 8601), null if not tracked
last_active_at string
When the sprite was last active/running (ISO 8601), null if not tracked

**RESPONSE CODES**

**200 Success**

401
Missing or invalid authentication
404
Sprite not found

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites/{name}" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
{
 "id": "01234567-89ab-cdef-0123-456789abcdef",
 "name": "my-dev-sprite",
 "status": "cold",
 "url": "https://name-random-alphanumeric.sprites.app",
 "url_settings": {
   "auth": "sprite"
 },
 "created_at": "2024-01-15T10:30:00Z",
 "organization": "my-org",
 "updated_at": "2024-01-15T14:22:00Z",
 "last_active_at": "2024-01-15T14:22:00Z",
 "last_started_at": "2024-01-15T14:20:00Z"
}
```


Destroy Sprite

### `DELETE /v1/sprites/{name}`

Delete a sprite and all associated resources

**PATH PARAMETERS**

name* string
Unique sprite name

**RESPONSE**

application/json

**RESPONSE CODES**

204
No content
401
Missing or invalid authentication
404
Sprite not found

```bash
curl -X DELETE \
 "https://api.sprites.dev/v1/sprites/{name}" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

Update Sprite

### `PUT /v1/sprites/{name}`

Update sprite settings such as URL authentication

**PATH PARAMETERS**

name* string

Unique sprite name

**REQUEST BODY**

application/json
url_settings*
URL access configuration to update
auth "sprite" | "public"
Authentication type (default: sprite)

**RESPONSE**

application/json
id* string
Unique sprite identifier (UUID)
name* string
Sprite name within the organization
organization* string
Organization slug
url* string
Sprite HTTP endpoint URL
url_settings
URL access configuration
auth* "sprite" | "public"
Authentication type
status* "cold" | "warm" | "running"
Runtime status
created_at* string
Creation timestamp (ISO 8601)
updated_at* string
Last update timestamp (ISO 8601)
last_started_at string
When the sprite machine last started (ISO 8601), null if not tracked

last_active_at string
When the sprite was last active/running (ISO 8601), null if not tracked

**RESPONSE CODES**

**200 Success**

400
Invalid request parameters
401
Missing or invalid authentication
404
Sprite not found

```bash
curl -X PUT \
 "https://api.sprites.dev/v1/sprites/{name}" \
 -H "Authorization: Bearer $SPRITES_TOKEN" \
 -H "Content-Type: application/json" \
 -d '{"url_settings":{"auth":"public"}}'
```

**200 Response**

```json
{
 "id": "01234567-89ab-cdef-0123-456789abcdef",
 "name": "my-dev-sprite",
 "status": "cold",
 "url": "https://name-random-alphanumeric.sprites.app",
 "url_settings": {
   "auth": "sprite"
 },
 "created_at": "2024-01-15T10:30:00Z",
 "organization": "my-org",
 "updated_at": "2024-01-15T14:22:00Z",
 "last_active_at": "2024-01-15T14:22:00Z",
 "last_started_at": "2024-01-15T14:20:00Z"
}
```

## Exec

Command Execution
Run commands inside Sprites over WebSocket connections. The
exec API is designed for both one-shot commands and long-
running interactive sessions.
Sessions persist across disconnections—start a dev server or
build, disconnect, and reconnect later to resume streaming
output. The binary protocol efficiently multiplexes stdin, stdout,
and stderr over a single connection.
Execute Command

### `WSS /v1/sprites/{name}/exec`

Execute a command in the sprite environment via WebSocket. Commands continue running after disconnect;
use max_run_after_disconnect to control timeout. Supports TTY and non-TTY modes.

**QUERY PARAMETERS**

Pass these as query string parameters when connecting to the WebSocket.
cmd* string
Command to execute (can be repeated for command + args)
id string
Session ID to attach to an existing session
path string
Explicit path to executable (defaults to first cmd value or bash)
tty bool
Enable TTY mode (default: false)
stdin bool

Enable stdin. TTY default: true, non-TTY default: false
cols int
Initial terminal columns (default: 80)
rows int
Initial terminal rows (default: 24)
max_run_after_disconnect duration
Max time to run after disconnect. TTY default: 0 (forever), non-TTY default: 10s
env string
Environment variables in KEY=VALUE format (can be repeated). If set, replaces the default
environment.

**JSON MESSAGES**

ResizeMessage Client → Server
type* "resize"
cols* non_neg_integer
New column count
rows* non_neg_integer
New row count
SessionInfoMessage Server → Client
type* "session_info"
session_id* String
Session ID
command* String
Command being executed
created* integer
Unix timestamp of session creation

cols* non_neg_integer
Terminal columns (TTY mode only)
rows* non_neg_integer
Terminal rows (TTY mode only)
is_owner* boolean
Whether this attachment owns the session
tty* boolean
Whether session is in TTY mode
ExitMessage Server → Client
type* "exit"
exit_code* integer
Process exit code
PortNotificationMessage Server → Client
type* "port_opened" | "port_closed"
Notification type
port* integer
Port number
address* String
Proxy URL for accessing the port
pid* integer
Process ID that opened/closed the port

**BINARY PROTOCOL**

In non-PTY mode, binary messages are prefixed with a stream identifier byte. In PTY mode, binary data is
sent raw without prefixes.
Binary Frame Format (non-PTY):

Stream ID (1 byte)
+
Payload (N bytes)
STREAM ID
NAME
DIRECTION
DESCRIPTION
0
stdin
client → server
Standard input data
1

```text
server → client
```

Standard output data
2
stderr
server → client
Standard error data
3
exit
server → client
Exit code (payload is exit code as byte)
4
stdin_eof
client → server
End of stdin stream

**RESPONSE CODES**

101
Switching Protocols - WebSocket connection established
400
Bad Request - Invalid WebSocket upgrade or missing parameters
404
Not Found - Resource not found

```bash
websocat \
 "wss://api.sprites.dev/v1/sprites/{name}/exec?path=/bin/bash&tty=true"
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

Binary Streams
→stdin (0x00 + data)
←stdout (0x01 + data)
←stderr (0x02 + data)
JSON Messages
Resize terminal (client → server):
{"type": "resize", "cols": 120, "rows": 40}
Port opened (server → client):
{"type": "port_opened", "port": 8080, "address": "0.0.0.0", "pid": 1234}

List Exec Sessions

### `GET /v1/sprites/{name}/exec`

List active exec sessions.

**RESPONSE**

application/json

**RESPONSE CODES**

**200 Success**

404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites/{name}/exec" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
[
 {
   "bytes_per_second": 125.5,
   "command": "bash",
   "created": "2026-01-05T10:30:00Z",
   "id": 1847,
   "is_active": true,
   "last_activity": "2026-01-05T10:35:00Z",
   "tty": true,
   "workdir": "/home/sprite/myproject"
 },
 {
   "bytes_per_second": 0,
   "command": "python -m http.server 8000",

   "created": "2026-01-05T09:15:00Z",
   "id": 1923,
   "is_active": false,
   "last_activity": "2026-01-05T09:20:00Z",
   "tty": false,
   "workdir": "/home/sprite/webapp"
 }
]
```

Execute Command

### `POST /v1/sprites/{name}/exec`

Execute a command via simple HTTP POST (non-TTY only). Simpler alternative for exec for environments that
can’t handle websockets.

**QUERY PARAMETERS**

cmd* string
Command to execute (can be repeated for command + args)
path string
Explicit path to executable (defaults to first cmd value or bash)
stdin bool
Enable stdin from request body (default: false)
env string
Environment variables in KEY=VALUE format (can be repeated)
dir string
Working directory for the command

**RESPONSE**

application/json

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/exec" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

Attach to Exec Session

### `WSS /v1/sprites/{name}/exec/{session_id}`

Attach to an existing exec session via WebSocket.

**JSON MESSAGES**

ResizeMessage Client → Server
type* "resize"
cols* non_neg_integer
New column count
rows* non_neg_integer
New row count
SessionInfoMessage Server → Client

type* "session_info"
session_id* String
Session ID
command* String
Command being executed
created* integer
Unix timestamp of session creation
cols* non_neg_integer
Terminal columns (TTY mode only)
rows* non_neg_integer
Terminal rows (TTY mode only)
is_owner* boolean
Whether this attachment owns the session
tty* boolean
Whether session is in TTY mode
ExitMessage Server → Client
type* "exit"
exit_code* integer
Process exit code

**SCROLLBACK BUFFER**

When you attach to a session, the server immediately sends the session's scrollback buffer as stdout
data. This allows you to see previous output that occurred while disconnected.

**RESPONSE CODES**

101
Switching Protocols - WebSocket connection established
400
Bad Request - Invalid WebSocket upgrade or missing parameters
404
Not Found - Resource not found

```bash
websocat \
 "wss://api.sprites.dev/v1/sprites/{name}/exec/{session_id}" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

Scrollback Buffer
On attach, the server sends the session's scrollback buffer as stdout data, allowing you to see
previous output from the command.
JSON Messages
Resize terminal (client → server):
{"type": "resize", "cols": 120, "rows": 40}
Kill Exec Session

### `POST /v1/sprites/{name}/exec/{session_id}/kill`

Kill an exec session by session ID. Returns streaming NDJSON with kill progress.

**QUERY PARAMETERS**

signal string
Signal to send (default: SIGTERM)
timeout duration
Timeout waiting for process to exit (default: 10s)

**RESPONSE**

application/x-ndjson
ExecKillSignalEvent

type* "signal"
message* String
Status message
signal* String
Signal name (e.g., SIGTERM)
pid* integer
Target process ID
ExecKillTimeoutEvent
type* "timeout"
message* String
Status message
ExecKillExitedEvent
type* "exited"
message* String
Status message
ExecKillKilledEvent
type* "killed"
message* String
Status message
ExecKillErrorEvent
type* "error"
message* String

Error message
ExecKillCompleteEvent
type* "complete"
exit_code* integer
Process exit code

**RESPONSE CODES**

200
Success - Streaming NDJSON response
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/exec/{session_id}/kill" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
[
 {
   "message": "Signaling SIGTERM to process group 1847",
   "pid": 1847,
   "signal": "SIGTERM",
   "type": "signal"
 },
 {
   "message": "Process exited",
   "type": "exited"
 },
 {
   "exit_code": 0,
   "type": "complete"
 }
]
```

## Services

Manage background services running in your Sprite
environment.
List Services

### `GET /v1/sprites/{name}/services`

List all configured services and their current state.

**RESPONSE**

application/json
name* string
Service name
cmd* string
Command to execute
args* string
Command arguments
needs* string
Service dependencies
http_port number
HTTP port for proxy routing
state
Current runtime state
name* string
Service name
status* string

stopped, starting, running, stopping, or failed
pid number
Process ID when running
started_at string
ISO 8601 timestamp
error string
Error message if failed

**RESPONSE CODES**

**200 Success**

404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites/{name}/services" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
[
 {
   "args": [
     "-D",
     "/var/lib/postgresql/data"
   ],
   "cmd": "postgres",
   "http_port": null,
   "name": "postgres",
   "needs": [],
   "state": {
     "name": "postgres",
     "pid": 1234,
     "started_at": "2026-01-05T08:00:00Z",
     "status": "running"
   }

 },
 {
   "args": [
     "-m",
     "http.server",
     "8000"
   ],
   "cmd": "python",
   "http_port": 8000,
   "name": "webapp",
   "needs": [
     "postgres"
   ],
   "state": {
     "name": "webapp",
     "pid": 1567,
     "started_at": "2026-01-05T08:01:00Z",
     "status": "running"
   }
 }
]
```

Get Service

### `GET /v1/sprites/{name}/services/{service_name}`

Get details of a specific service.

**RESPONSE**

application/json
name* string
Service name
cmd* string
Command to execute
args* string

Command arguments
needs* string
Service dependencies
http_port number
HTTP port for proxy routing
state
Current runtime state
name* string
Service name
status* string
stopped, starting, running, stopping, or failed
pid number
Process ID when running
started_at string
ISO 8601 timestamp
error string
Error message if failed

**RESPONSE CODES**

**200 Success**

404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites/{name}/services/{service_name}" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**


{
 "args": [
   "-m",
   "http.server",
   "8000"
 ],
 "cmd": "python",
 "http_port": 8000,
 "name": "webapp",
 "needs": [
   "postgres"
 ],
 "state": {
   "name": "webapp",
   "pid": 1567,
   "started_at": "2026-01-05T08:01:00Z",
   "status": "running"
 }
}
Create Service

### `PUT /v1/sprites/{name}/services/{service_name}`

Create or update a service definition.

**QUERY PARAMETERS**

duration duration
Time to monitor logs after starting (default: 5s)

**REQUEST BODY**

application/json
cmd* string
Command to execute

args* string
Command arguments
env map
Environment variables to add to the base service environment
dir string
Working directory for the service
needs* string
Service dependencies (started first)
http_port number
HTTP port for proxy routing

**RESPONSE**

application/json
name* string
Service name
cmd* string
Command to execute
args* string
Command arguments
needs* string
Service dependencies
http_port number
HTTP port for proxy routing
state
Current runtime state
name* string
Service name
status* string
stopped, starting, running, stopping, or failed

pid number
Process ID when running
started_at string
ISO 8601 timestamp
error string
Error message if failed

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X PUT \
 "https://api.sprites.dev/v1/sprites/{name}/services/{service_name}" \
 -H "Authorization: Bearer $SPRITES_TOKEN" \
 -H "Content-Type: application/json" \
 -d '{"args":["-m","http.server","8000"],"cmd":"python","http_port":8000
```

**200 Response**

```json
{
 "args": [
   "-m",
   "http.server",
   "8000"
 ],
 "cmd": "python",
 "http_port": 8000,
 "name": "webapp",
 "needs": [
   "postgres"
 ],
 "state": {
   "name": "webapp",

   "started_at": "2026-01-05T10:30:00Z",
   "status": "starting"
 }
}
```

Start Service

### `POST /v1/sprites/{name}/services/{service_name}/start`

Start a service. Returns streaming NDJSON with stdout/stderr.

**QUERY PARAMETERS**

duration duration
Time to monitor logs after starting (default: 5s)

**RESPONSE**

application/x-ndjson
ServiceLogStdoutEvent
type* "stdout"
data* String
Log line content
timestamp* integer
Unix milliseconds
ServiceLogStderrEvent
type* "stderr"
data* String
Log line content

timestamp* integer
Unix milliseconds
ServiceLogExitEvent
type* "exit"
exit_code* integer
Process exit code
timestamp* integer
Unix milliseconds
ServiceLogErrorEvent
type* "error"
data* String
Error message
timestamp* integer
Unix milliseconds
ServiceLogCompleteEvent
type* "complete"
timestamp* integer
Unix milliseconds
ServiceLogStartedEvent
type* "started"
timestamp* integer
Unix milliseconds

**RESPONSE CODES**


200
Success - Streaming NDJSON response
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/services/{service_name}/star
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
[
 {
   "timestamp": 1735988400000,
   "type": "started"
 },
 {
   "data": "Starting server...\n",
   "timestamp": 1735988400000,
   "type": "stdout"
 },
 {
   "data": "Listening on port 8000\n",
   "timestamp": 1735988401000,
   "type": "stdout"
 },
 {
   "log_files": {
     "stdout": "/.sprite/logs/services/webapp.log"
   },
   "timestamp": 1735988402000,
   "type": "complete"
 }
]
```


Stop Service

### `POST /v1/sprites/{name}/services/{service_name}/stop`

Stop a running service. Returns streaming NDJSON with service stop progress.

**QUERY PARAMETERS**

timeout duration
Timeout waiting for service to stop (default: 10s)

**RESPONSE**

application/x-ndjson
ServiceLogStoppingEvent
type* "stopping"
timestamp* integer
Unix milliseconds
ServiceLogStdoutEvent
type* "stdout"
data* String
Log line content
timestamp* integer
Unix milliseconds
ServiceLogStderrEvent
type* "stderr"
data* String
Log line content
timestamp* integer

Unix milliseconds
ServiceLogErrorEvent
type* "error"
data* String
Error message
timestamp* integer
Unix milliseconds
ServiceLogStoppedEvent
type* "stopped"
exit_code* integer
Process exit code
timestamp* integer
Unix milliseconds
ServiceLogCompleteEvent
type* "complete"
timestamp* integer
Unix milliseconds

**RESPONSE CODES**

200
Success - Streaming NDJSON response
404
Not Found - Resource not found
500
Internal Server Error

curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/services/{service_name}/stop
 -H "Authorization: Bearer $SPRITES_TOKEN"

**200 Response**

```json
[
 {
   "timestamp": 1735988400000,
   "type": "stopping"
 },
 {
   "exit_code": 0,
   "timestamp": 1735988401000,
   "type": "stopped"
 },
 {
   "log_files": {
     "stdout": "/.sprite/logs/services/webapp.log"
   },
   "timestamp": 1735988402000,
   "type": "complete"
 }
]
```

Restart Service

### `POST /v1/sprites/{name}/services/{service_name}/restart`

Restart a service (stop if running, then start). Returns streaming NDJSON with stop and start progress.

**QUERY PARAMETERS**

duration duration

Time to monitor logs after starting (default: 5s)

**RESPONSE**

application/x-ndjson
ServiceLogStoppingEvent
type* "stopping"
timestamp* integer
Unix milliseconds
ServiceLogStoppedEvent
type* "stopped"
exit_code* integer
Process exit code
timestamp* integer
Unix milliseconds
ServiceLogStdoutEvent
type* "stdout"
data* String
Log line content
timestamp* integer
Unix milliseconds
ServiceLogStderrEvent
type* "stderr"
data* String
Log line content
timestamp* integer

Unix milliseconds
ServiceLogExitEvent
type* "exit"
exit_code* integer
Process exit code
timestamp* integer
Unix milliseconds
ServiceLogErrorEvent
type* "error"
data* String
Error message
timestamp* integer
Unix milliseconds
ServiceLogCompleteEvent
type* "complete"
timestamp* integer
Unix milliseconds
ServiceLogStartedEvent
type* "started"
timestamp* integer
Unix milliseconds

**RESPONSE CODES**


200
Success - Streaming NDJSON response
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/services/{service_name}/rest
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

Get Service Logs

### `GET /v1/sprites/{name}/services/{service_name}/logs`

Stream logs for a service.

**QUERY PARAMETERS**

lines int
Number of lines to return from log buffer (default: all)
duration duration
Time to follow new logs (default: 0, no follow)

**RESPONSE**

application/x-ndjson
ServiceLogStdoutEvent
type* "stdout"
data* String

Log line content
timestamp* integer
Unix milliseconds
ServiceLogStderrEvent
type* "stderr"
data* String
Log line content
timestamp* integer
Unix milliseconds
ServiceLogExitEvent
type* "exit"
exit_code* integer
Process exit code
timestamp* integer
Unix milliseconds
ServiceLogErrorEvent
type* "error"
data* String
Error message
timestamp* integer
Unix milliseconds
ServiceLogCompleteEvent
type* "complete"

timestamp* integer
Unix milliseconds

**RESPONSE CODES**

200
Success - Streaming NDJSON response
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites/{name}/services/{service_name}/logs
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
[
 {
   "data": "Server started\n",
   "timestamp": 1735988400000,
   "type": "stdout"
 },
 {
   "data": "Handling request from 127.0.0.1\n",
   "timestamp": 1735988450000,
   "type": "stdout"
 },
 {
   "data": "Warning: slow query detected\n",
   "timestamp": 1735988455000,
   "type": "stderr"
 },
 {
   "log_files": {
     "stdout": "/.sprite/logs/services/webapp.log"
   },
   "timestamp": 1735988460000,
   "type": "complete"

 }
] Sprites
```

## File System

Filesystem
Read, write, and manage files within your Sprite environment.
Read File

### `GET /v1/sprites/{name}/fs/read`

Read file contents from the sprite filesystem. Returns raw file bytes.

**QUERY PARAMETERS**

path* string
Path to the file to read
workingDir* string
Working directory for resolving relative paths

**RESPONSE**

application/json

**RESPONSE CODES**

**200 Success**

404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites/{name}/fs/read" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**


Write File

### `PUT /v1/sprites/{name}/fs/write`

Write file contents to the sprite filesystem. Request body contains raw file bytes.

**QUERY PARAMETERS**

path* string
Path to the file to write
workingDir* string
Working directory for resolving relative paths
mode string
File permissions in octal (e.g., ‘0644’)
mkdir bool
Create parent directories if they don’t exist

**RESPONSE**

application/json
path* string
size* number
mode* string

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X PUT \
 "https://api.sprites.dev/v1/sprites/{name}/fs/write" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
{
 "size": 1,
 "mode": "example",
 "path": "example"
}
```

List Directory

### `GET /v1/sprites/{name}/fs/list`

List directory contents.

**QUERY PARAMETERS**

path* string
Path to the directory to list
workingDir* string
Working directory for resolving relative paths

**RESPONSE**

application/json
path* string
entries* Entry[]

count* number

**RESPONSE CODES**

**200 Success**

404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites/{name}/fs/list" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
{
 "count": 1,
 "path": "example",
 "entries": []
}
```

Delete File or Directory

### `DELETE /v1/sprites/{name}/fs/delete`

Delete a file or directory.

**RESPONSE**

application/json
deleted* string
count* number

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X DELETE \
 "https://api.sprites.dev/v1/sprites/{name}/fs/delete" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
{
 "count": 1,
 "deleted": "example"
}
```

Rename File or Directory

### `POST /v1/sprites/{name}/fs/rename`

Rename or move a file or directory.

**REQUEST BODY**

application/json
source* string
dest* string
workingDir* string
asRoot* boolean

**RESPONSE**

application/json
source* string
dest* string

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/fs/rename" \
 -H "Authorization: Bearer $SPRITES_TOKEN" \
 -H "Content-Type: application/json" \
 -d '{"asRoot":false,"dest":"example","source":"example","workingDir":"e
```

**200 Response**

```json
{
 "source": "example",
 "dest": "example"
}
```

Copy File or Directory

### `POST /v1/sprites/{name}/fs/copy`


Copy a file or directory.

**REQUEST BODY**

application/json
source* string
dest* string
workingDir* string
recursive* boolean
preserveAttrs* boolean
asRoot* boolean

**RESPONSE**

application/json
copied* CopyResult[]
count* number
totalBytes* number

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/fs/copy" \
 -H "Authorization: Bearer $SPRITES_TOKEN" \
```


 -H "Content-Type: application/json" \
 -d '{"asRoot":false,"dest":"example","preserveAttrs":false,"recursive":

**200 Response**

```json
{
 "count": 1,
 "copied": [],
 "totalBytes": 1
}
```

Change File Mode

### `POST /v1/sprites/{name}/fs/chmod`

Change file or directory permissions.

**REQUEST BODY**

application/json
path* string
workingDir* string
mode* string
recursive* boolean
asRoot* boolean

**RESPONSE**

application/json
affected* ChmodResult[]

count* number

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/fs/chmod" \
 -H "Authorization: Bearer $SPRITES_TOKEN" \
 -H "Content-Type: application/json" \
 -d '{"asRoot":false,"mode":"example","path":"example","recursive":false
```

**200 Response**

```json
{
 "count": 1,
 "affected": []
}
```

Change File Owner

### `POST /v1/sprites/{name}/fs/chown`

Change file or directory ownership.

**REQUEST BODY**

application/json
path* string

workingDir* string
uid* interface{}
gid* interface{}
recursive* boolean
asRoot* boolean

**RESPONSE**

application/json
affected* ChownResult[]
count* number

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/fs/chown" \
 -H "Authorization: Bearer $SPRITES_TOKEN" \
 -H "Content-Type: application/json" \
 -d '{"asRoot":false,"gid":null,"path":"example","recursive":false,"uid"
```

**200 Response**

```json
{
 "count": 1,
 "affected": []
}
```


Watch Filesystem

### `WSS /v1/sprites/{name}/fs/watch`

Watch for filesystem changes via WebSocket.

**JSON MESSAGES**

WatchMessage Client → Server
type* String
paths [String]
recursive boolean
workingDir String
path String
event String
timestamp String
size integer
isDir boolean
message String
WatchMessage Server → Client
type* String
paths [String]

recursive boolean
workingDir String
path String
event String
timestamp String
size integer
isDir boolean
message String

**BINARY PROTOCOL**

In non-PTY mode, binary messages are prefixed with a stream identifier byte. In PTY mode, binary data is
sent raw without prefixes.
Binary Frame Format (non-PTY):
Stream ID (1 byte)
+
Payload (N bytes)
STREAM ID
NAME
DIRECTION
DESCRIPTION
0
stdin
client → server
Standard input data
1

```text
server → client
```

Standard output data
2
stderr
server → client
Standard error data
3
exit
server → client
Exit code (payload is exit code as byte)
4
stdin_eof
client → server
End of stdin stream

**RESPONSE CODES**

101
Switching Protocols - WebSocket connection established
400
Bad Request - Invalid WebSocket upgrade or missing parameters
404
Not Found - Resource not found

```bash
websocat \
 "wss://api.sprites.dev/v1/sprites/{name}/fs/watch?path=/bin/bash&tty=tr
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

Binary Streams
→stdin (0x00 + data)
←stdout (0x01 + data)
←stderr (0x02 + data)
JSON Messages
Resize terminal (client → server):
{"type": "resize", "cols": 120, "rows": 40}
Port opened (server → client):
{"type": "port_opened", "port": 8080, "address": "0.0.0.0", "pid": 1234}

## Checkpoints

Checkpoints capture your Sprite’s complete filesystem state for
instant rollback. They’re live snapshots—creation takes
milliseconds with no interruption to running processes.
Use checkpoints before risky operations, to create reproducible
environments, or to share known-good states across a team.
Copy-on-write storage keeps incremental checkpoints small;
you only store what changed.
Create Checkpoint

### `POST /v1/sprites/{name}/checkpoint`

Create a new checkpoint of the current sprite state. Returns streaming NDJSON progress.

**REQUEST BODY**

application/json
comment string

**RESPONSE**

application/x-ndjson
StreamInfoEvent
type* "info"
data* String
Status message
time* DateTime
Timestamp

StreamErrorEvent
type* "error"
error* String
Error description
time* DateTime
Timestamp
StreamCompleteEvent
type* "complete"
data* String
Completion message
time* DateTime
Timestamp

**RESPONSE CODES**

200
Success - Streaming NDJSON response
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/checkpoint" \
 -H "Authorization: Bearer $SPRITES_TOKEN" \
 -H "Content-Type: application/json" \
 -d '{"comment":"Before deploying v2.0"}'
```

**200 Response**

```json
[
 {
   "data": "Creating checkpoint...",

   "time": "2026-01-05T10:30:00Z",
   "type": "info"
 },
 {
   "data": "Stopping services...",
   "time": "2026-01-05T10:30:00Z",
   "type": "info"
 },
 {
   "data": "Saving filesystem state...",
   "time": "2026-01-05T10:30:00Z",
   "type": "info"
 },
 {
   "data": "Checkpoint v8 created",
   "time": "2026-01-05T10:30:00Z",
   "type": "complete"
 }
]
```

List Checkpoints

### `GET /v1/sprites/{name}/checkpoints`

List all checkpoints.

**RESPONSE**

application/json
id* string
Checkpoint identifier (e.g., v7)
create_time* string
When the checkpoint was created
source_id string
Parent checkpoint ID

comment string
User-provided description
health string
Health status (empty = healthy, “mount_failed” = unhealthy)

**RESPONSE CODES**

**200 Success**

404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites/{name}/checkpoints" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
[
 {
   "comment": "Before database migration",
   "create_time": "2026-01-05T10:30:00Z",
   "id": "v7"
 },
 {
   "comment": "Stable state",
   "create_time": "2026-01-04T15:00:00Z",
   "id": "v6"
 },
 {
   "comment": "",
   "create_time": "2026-01-04T09:00:00Z",
   "id": "v5"
 }
]
```


Get Checkpoint

### `GET /v1/sprites/{name}/checkpoints/{checkpoint_id}`

Get details of a specific checkpoint.

**RESPONSE**

application/json
id* string
Checkpoint identifier (e.g., v7)
create_time* string
When the checkpoint was created
source_id string
Parent checkpoint ID
comment string
User-provided description
health string
Health status (empty = healthy, “mount_failed” = unhealthy)

**RESPONSE CODES**

**200 Success**

404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites/{name}/checkpoints/{checkpoint_id}"
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**


{
 "comment": "Before database migration",
 "create_time": "2026-01-05T10:30:00Z",
 "id": "v7"
}
Restore Checkpoint

### `POST /v1/sprites/{name}/checkpoints/{checkpoint_id}/restore`

Restore to a specific checkpoint. Returns streaming NDJSON progress.

**RESPONSE**

application/x-ndjson
StreamInfoEvent
type* "info"
data* String
Status message
time* DateTime
Timestamp
StreamErrorEvent
type* "error"
error* String
Error description
time* DateTime
Timestamp

StreamCompleteEvent
type* "complete"
data* String
Completion message
time* DateTime
Timestamp

**RESPONSE CODES**

200
Success - Streaming NDJSON response
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/checkpoints/{checkpoint_id}/
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
[
 {
   "data": "Restoring to checkpoint v5...",
   "time": "2026-01-05T10:30:00Z",
   "type": "info"
 },
 {
   "data": "Stopping services...",
   "time": "2026-01-05T10:30:00Z",
   "type": "info"
 },
 {
   "data": "Restoring filesystem...",
   "time": "2026-01-05T10:30:00Z",
   "type": "info"

 },
 {
   "data": "Restored to v5",
   "time": "2026-01-05T10:30:00Z",
   "type": "complete"
 }
]
```

## Port Proxy

Tunnel TCP connections directly to services running inside your
Sprite. After a brief WebSocket handshake, the connection
becomes a transparent relay to any port.
Use this to access dev servers, databases, or any TCP service as
if it were running locally. The proxy handles connection setup;
your client speaks directly to the target service.
TCP Proxy

### `WSS /v1/sprites/{name}/proxy`

Establish a WebSocket tunnel to a port inside the sprite environment.

**JSON MESSAGES**

After connecting, send a JSON init message to specify the target host and port.
ProxyInitMessage Client → Server
host* String
Target hostname (typically “localhost”)
port* integer
Target port (1-65535)

**BINARY PROTOCOL**

After the JSON handshake completes, the connection becomes a raw TCP relay. Binary data is forwarded
directly without any framing or prefixes.
NAME
DIRECTION
DESCRIPTION
data
client → server
Raw bytes sent to the target TCP port

NAME
DIRECTION
DESCRIPTION
data
server → client
Raw bytes received from the target TCP port

**RESPONSE CODES**

101
Switching Protocols - WebSocket connection established
400
Bad Request - Invalid WebSocket upgrade or missing parameters
404
Not Found - Resource not found

```bash
websocat \
 "wss://api.sprites.dev/v1/sprites/{name}/proxy" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

Protocol Flow
1. Send JSON init message
2. Receive JSON response
3. Binary TCP relay begins
JSON Messages
Init connection (client → server):
{"host": "localhost", "port": 8080}
Connection response (server → client):
{"status": "connected", "target": "localhost:8080"}

## Network

Network Policy
Control outbound network access using DNS-based filtering.
Policies define which domains sprites can reach, with support
for exact matches, wildcard subdomains, and preset rule
bundles.
Changes apply immediately—existing connections to newly-
blocked domains are terminated. Failed DNS lookups return
REFUSED for fast failure.
Get Network Policy

### `GET /v1/sprites/{name}/policy/network`

Get the current network policy configuration.

**RESPONSE**

application/json
rules* NetworkPolicyRule[]
List of network policy rules
domain string
Domain pattern (e.g., *.github.com)
action string
allow or deny
include string
Include rules from preset

**RESPONSE CODES**

**200 Success**

404
Not Found - Resource not found

500
Internal Server Error

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites/{name}/policy/network" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

```json
{
 "rules": [
   {
     "action": "allow",
     "domain": "github.com"
   },
   {
     "action": "allow",
     "domain": "*.npmjs.org"
   },
   {
     "action": "deny",
     "domain": "*"
   }
 ]
}
```

Set Network Policy

### `POST /v1/sprites/{name}/policy/network`

Update the network policy configuration.

**REQUEST BODY**

application/json
rules* NetworkPolicyRule[]

List of network policy rules
domain string
Domain pattern (e.g., *.github.com)
action string
allow or deny
include string
Include rules from preset

**RESPONSE**

application/json

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/policy/network" \
 -H "Authorization: Bearer $SPRITES_TOKEN" \
 -H "Content-Type: application/json" \
 -d '{"rules":[{"action":"allow","domain":"github.com"},{"action":"allow
```

**200 Response**

```json
{
 "rules": [
   {
     "action": "allow",
     "domain": "github.com"
   }
 ]
}
```


Get Privileges Policy

### `GET /v1/sprites/{name}/policy/privileges`

Get the current privileges policy configuration (capability and device restrictions).

**RESPONSE**

application/json

**RESPONSE CODES**

**200 Success**

404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites/{name}/policy/privileges" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

Set Privileges Policy

### `POST /v1/sprites/{name}/policy/privileges`

Update the privileges policy configuration to restrict capabilities or devices.

**RESPONSE**

application/json

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/policy/privileges" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

Delete Privileges Policy

### `DELETE /v1/sprites/{name}/policy/privileges`

Remove privileges policy to revert to default (unrestricted) behavior.

**RESPONSE**

application/json

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X DELETE \
 "https://api.sprites.dev/v1/sprites/{name}/policy/privileges" \
```


 -H "Authorization: Bearer $SPRITES_TOKEN"

**200 Response**

Get Resources Policy

### `GET /v1/sprites/{name}/policy/resources`

Get the current resources policy configuration (memory limits).

**RESPONSE**

application/json

**RESPONSE CODES**

**200 Success**

404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X GET \
 "https://api.sprites.dev/v1/sprites/{name}/policy/resources" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

Set Resources Policy

### `POST /v1/sprites/{name}/policy/resources`


Update the resources policy configuration to set memory limits.

**RESPONSE**

application/json

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/policy/resources" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**

Delete Resources Policy

### `DELETE /v1/sprites/{name}/policy/resources`

Remove resources policy to revert to default behavior.

**RESPONSE**

application/json

**RESPONSE CODES**

**200 Success**

400
Bad Request - Invalid request body
404
Not Found - Resource not found
500
Internal Server Error

```bash
curl -X DELETE \
 "https://api.sprites.dev/v1/sprites/{name}/policy/resources" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**
