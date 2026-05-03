/**
 * Chat HTTP client — slice 8 §8.
 *
 * v1 ships polling-based: `useChat` queries every 2s. Live streaming
 * via `/ws/web/chats/{id}` lands in Phase 8b. The HTTP shapes mirror
 * the orchestrator's `ChatResponse` / `ChatTurnResponse` Pydantic
 * models in `apps/orchestrator/src/orchestrator/routes/chats.py`.
 */

import { api } from './api';

export interface ChatResponse {
  id: string;
  title: string;
  status:
    | 'pending'
    | 'running'
    | 'awaiting_input'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'archived';
  initial_prompt: string;
  claude_session_id: string | null;
  tokens_input: number;
  tokens_output: number;
  last_alive_at: string | null;
  created_at: string;
}

export interface ChatTurnResponse {
  id: string;
  chat_id: string;
  is_follow_up: boolean;
  prompt: string;
  enhanced_prompt: string | null;
  status:
    | 'queued'
    | 'running'
    | 'awaiting_input'
    | 'completed'
    | 'failed'
    | 'cancelled';
  started_at: string;
  ended_at: string | null;
}

export interface CreateChatResponse {
  chat: ChatResponse;
  turn: ChatTurnResponse;
  enhanced: boolean;
  used_topics: string[];
}

export interface FollowUpResponse {
  turn: ChatTurnResponse;
  enhanced: boolean;
  used_topics: string[];
}

const baseUrl = (): string => {
  const v = import.meta.env.VITE_ORCHESTRATOR_BASE_URL;
  if (!v) throw new Error('VITE_ORCHESTRATOR_BASE_URL is not set');
  return v;
};

const credentials: RequestCredentials = 'include';

async function fetchJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${baseUrl()}${path}`, {
    ...init,
    credentials,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text || res.statusText}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function createChat(prompt: string): Promise<CreateChatResponse> {
  return fetchJson<CreateChatResponse>('/api/chats', {
    method: 'POST',
    body: JSON.stringify({ prompt }),
  });
}

export async function listChats(): Promise<ChatResponse[]> {
  return fetchJson<ChatResponse[]>('/api/chats');
}

export async function getChat(chatId: string): Promise<ChatResponse> {
  return fetchJson<ChatResponse>(`/api/chats/${encodeURIComponent(chatId)}`);
}

export async function listChatTurns(chatId: string): Promise<ChatTurnResponse[]> {
  return fetchJson<ChatTurnResponse[]>(
    `/api/chats/${encodeURIComponent(chatId)}/turns`,
  );
}

export async function sendMessage(
  chatId: string,
  prompt: string,
): Promise<FollowUpResponse> {
  return fetchJson<FollowUpResponse>(
    `/api/chats/${encodeURIComponent(chatId)}/messages`,
    {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    },
  );
}

export async function cancelChat(chatId: string): Promise<void> {
  await fetchJson<void>(
    `/api/chats/${encodeURIComponent(chatId)}/cancel`,
    { method: 'POST' },
  );
}

// `api` is intentionally unused here — reserved for when we migrate to
// the typed openapi-fetch client once `gen:api-types` regenerates with
// the chats routes included.
void api;
