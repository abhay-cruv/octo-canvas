# Sprites API v1 — PYTHON examples

Sprite environment: **v0.0.1-rc43**. Source: PDFs in `python/`.

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
$ pip install sprites-py
1
Create a sprite
import os
from sprites import SpritesClient
client = SpritesClient(os.environ["SPRITE_TOKEN"])
client.create_sprite(os.environ["SPRITE_NAME"])
2
Run Python
output = client.sprite(os.environ["SPRITE_NAME"]).command("python", "-c",
print(output.decode(), end="")
3
Clean up
client.delete_sprite(os.environ["SPRITE_NAME"])
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

```python

Execute commands inside sprites via WebSocket. Stream stdin/stdout and manage processes.
```

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

```python
import os
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
client = SpritesClient(token)
```

```python

client.create_sprite(sprite_name, labels=["prod"])
print(f"Sprite '{sprite_name}' created")
```

```text
Sprite 'example-silver-pulse' created
```

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

```python
import json
import os
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
client = SpritesClient(token)
sprites = client.list_sprites()
result = []
for s in sprites.sprites:
   item = {"name": s.name}
   if s.id:
       item["id"] = s.id
   if s.status:
       item["status"] = s.status
   if s.url:
       item["url"] = s.url
   result.append(item)
print(json.dumps(result, indent=2))
```

```text
[
  {
    "name": "example-quantum-runner",
    "id": "sprite-4d486550-1953-4dfd-a452-cdabfd4a6663",
    "status": "running",
    "url": "https://example-quantum-runner-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771624836-9052",
    "id": "sprite-86098123-7007-4ad3-82c1-48811afb3a7b",
    "status": "cold",
    "url": "https://test-sprite-1771624836-9052-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771624837-8915",
    "id": "sprite-dd22a9bc-2241-4a2e-a8aa-eb4ba2c128b1",
    "status": "cold",
    "url": "https://test-sprite-1771624837-8915-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771624847-6027",
    "id": "sprite-7465d2c9-8bf4-4a67-8786-63483ac93ed5",
    "status": "cold",
    "url": "https://test-sprite-1771624847-6027-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771626415-8472",
    "id": "sprite-6a16fa07-9261-4885-bd28-61902aba7981",
    "status": "cold",
    "url": "https://test-sprite-1771626415-8472-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771626431-4374",
    "id": "sprite-83d17547-cb38-4754-9430-5500850e5365",
    "status": "cold",
    "url": "https://test-sprite-1771626431-4374-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771653089-5980",
    "id": "sprite-8a6dbddd-5cad-4841-aaf7-d69209c32a15",
    "status": "cold",
    "url": "https://test-sprite-1771653089-5980-bhmkr.sprites.app"

  },
  {
    "name": "test-sprite-1771653089-8503",
    "id": "sprite-4ded160d-7f23-4f14-82c6-2834221549d4",
    "status": "cold",
    "url": "https://test-sprite-1771653089-8503-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771693602-6421",
    "id": "sprite-0ccdbf15-60b4-429f-af25-8491487c9319",
    "status": "cold",
    "url": "https://test-sprite-1771693602-6421-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771693604-1670",
    "id": "sprite-7f9e7e77-a86a-44fb-9805-359785bb6ee9",
    "status": "cold",
    "url": "https://test-sprite-1771693604-1670-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771693694-9604",
    "id": "sprite-f940fb27-7c43-41e6-8486-012d7bbb2f4c",
    "status": "cold",
    "url": "https://test-sprite-1771693694-9604-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771694158-1458",
    "id": "sprite-c41022a9-6135-4743-9b61-48f73341f062",
    "status": "cold",
    "url": "https://test-sprite-1771694158-1458-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771694158-5041",
    "id": "sprite-ed2b442d-4119-49cd-a0aa-2c4151478f75",
    "status": "cold",
    "url": "https://test-sprite-1771694158-5041-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771694174-4002",
    "id": "sprite-dd4cfd51-b5ac-418f-ba03-edf454f12b90",
    "status": "cold",
    "url": "https://test-sprite-1771694174-4002-bhmkr.sprites.app"
  },
  {

    "name": "test-sprite-1771694894-6136",
    "id": "sprite-77292e12-a892-4e2c-95b7-0f3946a47c61",
    "status": "cold",
    "url": "https://test-sprite-1771694894-6136-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771694909-8178",
    "id": "sprite-a60c5ffa-ff7d-4f3d-9073-478e6b2d1f3e",
    "status": "cold",
    "url": "https://test-sprite-1771694909-8178-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771704217-6251",
    "id": "sprite-3c51ee52-e33d-4093-b32e-54bb13a58c50",
    "status": "cold",
    "url": "https://test-sprite-1771704217-6251-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771704308-3185",
    "id": "sprite-986c02ca-4716-4f33-bc32-24bba285d69d",
    "status": "cold",
    "url": "https://test-sprite-1771704308-3185-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771705638-8642",
    "id": "sprite-90dc16de-3935-4bc2-9a79-612cee8bd051",
    "status": "cold",
    "url": "https://test-sprite-1771705638-8642-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771725351-9636",
    "id": "sprite-a53d1165-5b9b-4077-9062-0df9b0c9f9bd",
    "status": "cold",
    "url": "https://test-sprite-1771725351-9636-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771725353-3198",
    "id": "sprite-6ce5fd22-d4d3-4d8c-9bcb-43ece7cd9301",
    "status": "cold",
    "url": "https://test-sprite-1771725353-3198-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771725368-9209",
    "id": "sprite-50eed3bc-b013-4c93-ab2d-6aebbe1d0599",

    "status": "cold",
    "url": "https://test-sprite-1771725368-9209-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771782286-3900",
    "id": "sprite-9446ed2c-545b-4c89-b7e3-2e956a85f3eb",
    "status": "cold",
    "url": "https://test-sprite-1771782286-3900-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771782288-7894",
    "id": "sprite-cc95d60d-85b6-4edf-9182-c45d29daeb69",
    "status": "cold",
    "url": "https://test-sprite-1771782288-7894-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771782298-5000",
    "id": "sprite-6e232bb7-d106-4d0c-bb80-faf104441d02",
    "status": "cold",
    "url": "https://test-sprite-1771782298-5000-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771790376-773",
    "id": "sprite-3b7d8038-1cc6-48ca-be4a-e6b5ff35bf7b",
    "status": "cold",
    "url": "https://test-sprite-1771790376-773-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771796319-6958",
    "id": "sprite-e8686138-27a2-4809-88be-2d780f235147",
    "status": "cold",
    "url": "https://test-sprite-1771796319-6958-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771858766-2907",
    "id": "sprite-1164cfd0-26be-4e83-9f3a-d25a7fbd69bc",
    "status": "cold",
    "url": "https://test-sprite-1771858766-2907-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771858863-2453",
    "id": "sprite-2cf7126e-03e2-4452-b742-c54dff55bde7",
    "status": "cold",
    "url": "https://test-sprite-1771858863-2453-bhmkr.sprites.app"

  },
  {
    "name": "test-sprite-1771888887-7446",
    "id": "sprite-90a979da-2882-4fd5-a850-edf79c37d278",
    "status": "cold",
    "url": "https://test-sprite-1771888887-7446-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771888952-9398",
    "id": "sprite-7643e8e7-3bce-48fb-bed8-0233fa92f2c5",
    "status": "cold",
    "url": "https://test-sprite-1771888952-9398-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771947248-8781",
    "id": "sprite-13c3f9b3-5dd8-470b-8657-edf0bc687688",
    "status": "cold",
    "url": "https://test-sprite-1771947248-8781-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771952284-2833",
    "id": "sprite-47cfe9c3-d904-4470-abe1-c3cc74c46912",
    "status": "cold",
    "url": "https://test-sprite-1771952284-2833-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771952373-5835",
    "id": "sprite-260aab65-529e-4f2a-8c05-935f9dc84abd",
    "status": "cold",
    "url": "https://test-sprite-1771952373-5835-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1771952500-2821",
    "id": "sprite-0277cd5a-6e80-416f-afc8-3bbca5c17907",
    "status": "cold",
    "url": "https://test-sprite-1771952500-2821-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772025826-41",
    "id": "sprite-9f5f08b6-58d8-454b-886e-5741c2bf5731",
    "status": "cold",
    "url": "https://test-sprite-1772025826-41-bhmkr.sprites.app"
  },
  {

    "name": "test-sprite-1772038367-6138",
    "id": "sprite-8aad908a-c30b-4d82-9ac6-78eac3aae5dc",
    "status": "cold",
    "url": "https://test-sprite-1772038367-6138-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772058198-8662",
    "id": "sprite-7958328f-a5a0-450e-afa9-be6768826176",
    "status": "cold",
    "url": "https://test-sprite-1772058198-8662-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772123170-148",
    "id": "sprite-6c6221c7-5fcb-44a4-a6b9-49f2866980e8",
    "status": "cold",
    "url": "https://test-sprite-1772123170-148-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772161407-3917",
    "id": "sprite-3ff4e2ab-4e56-4d0d-bbec-2a9df754c360",
    "status": "cold",
    "url": "https://test-sprite-1772161407-3917-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772207764-8099",
    "id": "sprite-61e53fe7-b4c3-46e1-8087-c73eaea00c52",
    "status": "cold",
    "url": "https://test-sprite-1772207764-8099-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772207991-9371",
    "id": "sprite-c0ceb652-bb1d-4cec-8767-3f9acdbd50c1",
    "status": "cold",
    "url": "https://test-sprite-1772207991-9371-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772208011-8001",
    "id": "sprite-c3c50c92-5a55-402e-b56e-2b5b8c3ea542",
    "status": "cold",
    "url": "https://test-sprite-1772208011-8001-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772208212-2700",
    "id": "sprite-050c8285-3c95-4082-af07-6c5dc0368409",

    "status": "cold",
    "url": "https://test-sprite-1772208212-2700-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772208212-7420",
    "id": "sprite-d5c4a28d-8ec6-4f50-8c38-d233f03e1346",
    "status": "cold",
    "url": "https://test-sprite-1772208212-7420-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772208219-1644",
    "id": "sprite-99d5dd2b-e4dd-47e3-ae88-9fedb102313a",
    "status": "cold",
    "url": "https://test-sprite-1772208219-1644-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772208229-253",
    "id": "sprite-e60f5884-436d-441e-b4be-e274f1b37481",
    "status": "cold",
    "url": "https://test-sprite-1772208229-253-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772208242-2217",
    "id": "sprite-248dad1a-ea82-4b2b-81a9-31ad75d3d77e",
    "status": "cold",
    "url": "https://test-sprite-1772208242-2217-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772208248-9215",
    "id": "sprite-5a683a2f-96c6-4c75-b6c3-23dd037f0708",
    "status": "cold",
    "url": "https://test-sprite-1772208248-9215-bhmkr.sprites.app"
  },
  {
    "name": "test-sprite-1772208249-4836",
    "id": "sprite-84e6392c-23bb-476c-bfde-50541bbec569",
    "status": "cold",
    "url": "https://test-sprite-1772208249-4836-bhmkr.sprites.app"
  }
]
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

```python
import json
import os
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
client = SpritesClient(token)
sprite = client.get_sprite(sprite_name)
result = {"name": sprite.name}
if sprite.id:
   result["id"] = sprite.id
if sprite.status:
   result["status"] = sprite.status
if sprite.url:
   result["url"] = sprite.url
print(json.dumps(result, indent=2))
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

```python
import os
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
client = SpritesClient(token)
client.delete_sprite(sprite_name)
print(f"Sprite '{sprite_name}' destroyed")
```

```text
Sprite 'example-silver-pulse' destroyed
```

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

```python
import os
from sprites import SpritesClient, URLSettings
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
client = SpritesClient(token)
client.update_sprite(sprite_name, url_settings=URLSettings(auth="public")
print("Sprite updated")
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

```python

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
```

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

```python
import os
import sys
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
# Start a command that runs for 30s (TTY sessions stay alive after discon
cmd = sprite.command(
   "python", "-c",
   "import time; print('Server ready on port 8080', flush=True); time.sl
)
cmd.tty = True  # TTY sessions are detachable
cmd.stdout = sys.stdout.buffer  # Stream output directly
cmd.timeout = 2  # Disconnect after 2 seconds (session keeps running)
try:
```

```python

   cmd.run()
except Exception:
   pass  # Timeout is expected - we disconnect while session continues
```

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

```python
import json
import os
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
sessions = sprite.list_sessions()
result = []
for s in sessions:
```

```python

   item = {
       "id": s.id,
       "command": s.command,
       "is_active": s.is_active,
       "tty": s.tty,
   }
   result.append(item)
print(json.dumps(result, indent=2))
```

```text
Execute Command
```

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
Python example unavailable
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

```python
import os
import sys
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
# Find the session from exec example
sessions = sprite.list_sessions()
target_session = None
for s in sessions:
   if "time.sleep" in s.command or "python" in s.command:
       target_session = s
       break
if not target_session:
   print("No running session found")
   sys.exit(1)
print(f"Attaching to session {target_session.id}...")
# Attach and read buffered output (includes data from before we connected
cmd = sprite.attach_session(target_session.id)
cmd.stdout = sys.stdout.buffer
cmd.timeout = 2
try:
   cmd.run()
except Exception:
   pass  # Timeout is expected
```

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
Python example unavailable
```


curl -X POST \
 "https://api.sprites.dev/v1/sprites/{name}/exec/{session_id}/kill" \
 -H "Authorization: Bearer $SPRITES_TOKEN"

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

```python

stopped, starting, running, stopping, or failed
pid number
```

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

```python
import json
import os
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
services = sprite.list_services()
result = []
for svc in services:
   item = {"name": svc.name, "cmd": svc.cmd}
   if svc.state:
       item["status"] = svc.state.status
   result.append(item)
print(json.dumps(result, indent=2))
```

```text
Get Service
```

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

```python
import json
import os
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
service_name = os.environ["SERVICE_NAME"]
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
svc = sprite.get_service(service_name)
result = {"name": svc.name, "cmd": svc.cmd}
if svc.state:
   result["status"] = svc.state.status
print(json.dumps(result, indent=2))
```

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

```python
import json
import os
from sprites import SpritesClient
from sprites.services import create_service
```

```python

token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
service_name = os.environ["SERVICE_NAME"]
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
stream = create_service(
   sprite,
   name=service_name,
   cmd="python",
   args=["-m", "http.server", "8000"],
   http_port=8000,
)
for event in stream:
   print(json.dumps({"type": event.type, "timestamp": event.timestamp}))
```

```text
Start Service
```

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

```python
import json
import os
from sprites import SpritesClient
from sprites.services import start_service
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
service_name = os.environ["SERVICE_NAME"]
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
stream = start_service(sprite, name=service_name)
```

```python

for event in stream:
   print(json.dumps({"type": event.type, "timestamp": event.timestamp}))
```

```text
Stop Service
```

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

```python
import json
import os
from sprites import SpritesClient
from sprites.services import stop_service
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
service_name = os.environ["SERVICE_NAME"]
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
stream = stop_service(sprite, name=service_name)
for event in stream:
   print(json.dumps({"type": event.type, "timestamp": event.timestamp}))
```

```text
Restart Service
```

### `POST /v1/sprites/{name}/services/{service_name}/restart`

Restart a service (stop if running, then start). Returns streaming NDJSON with stop and start progress.

**QUERY PARAMETERS**

```python

duration duration
Time to monitor logs after starting (default: 5s)
```

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
Python example unavailable
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
Python example unavailable
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
]
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
Python example unavailable
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
Python example unavailable
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
Python example unavailable
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
Python example unavailable
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
Python example unavailable
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
Python example unavailable
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
Python example unavailable
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
Python example unavailable
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
Python example unavailable
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

```python
import json
import os
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
stream = sprite.create_checkpoint("my-checkpoint")
```

```python

for msg in stream:
   print(json.dumps({"type": msg.type, "data": msg.data}))
```

```text
List Checkpoints
```

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

```python
import json
import os
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
checkpoints = sprite.list_checkpoints()
result = []
for cp in checkpoints:
   item = {"id": cp.id, "create_time": cp.create_time.isoformat().replac
   if cp.comment:
       item["comment"] = cp.comment
   result.append(item)
print(json.dumps(result, indent=2))
```

```text
Get Checkpoint
```

### `GET /v1/sprites/{name}/checkpoints/{checkpoint_id}`

Get details of a specific checkpoint.

**RESPONSE**

application/json

```python

id* string
```

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

```python
import json
import os
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
checkpoint_id = os.environ.get("CHECKPOINT_ID", "v1")
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
checkpoint = sprite.get_checkpoint(checkpoint_id)
result = {
   "id": checkpoint.id,
   "create_time": checkpoint.create_time.isoformat().replace("+00:00", "
}
```

```python

if checkpoint.comment:
   result["comment"] = checkpoint.comment
print(json.dumps(result, indent=2))
```

```text
Restore Checkpoint
```

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

```python
import json
import os
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
checkpoint_id = os.environ.get("CHECKPOINT_ID", "v1")
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
stream = sprite.restore_checkpoint(checkpoint_id)
for msg in stream:
   print(json.dumps({"type": msg.type, "data": msg.data}))
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
Python example unavailable
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

```python

500
```

Internal Server Error

```python
import json
import os
from sprites import SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
policy = sprite.get_network_policy()
result = {
   "rules": [
       {"domain": rule.domain, "action": rule.action}
       for rule in policy.rules
   ]
}
print(json.dumps(result, indent=2))
```

```text
Set Network Policy
```

### `POST /v1/sprites/{name}/policy/network`

Update the network policy configuration.

**REQUEST BODY**

application/json

```python

rules* NetworkPolicyRule[]
List of network policy rules
domain string
```

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

```python
import os
from sprites import NetworkPolicy, PolicyRule, SpritesClient
token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]
client = SpritesClient(token)
sprite = client.sprite(sprite_name)
policy = NetworkPolicy(
   rules=[
       PolicyRule(domain="api.github.com", action="allow"),
       PolicyRule(domain="*.npmjs.org", action="allow"),
   ]
)
sprite.update_network_policy(policy)
```

```python

print("Network policy updated")
```

```text
Get Privileges Policy
```

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
Python example unavailable
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
Python example unavailable
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
Python example unavailable
curl -X DELETE \
 "https://api.sprites.dev/v1/sprites/{name}/policy/privileges" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

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
Python example unavailable
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
Python example unavailable
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
Python example unavailable
curl -X DELETE \
 "https://api.sprites.dev/v1/sprites/{name}/policy/resources" \
 -H "Authorization: Bearer $SPRITES_TOKEN"
```

**200 Response**
