// Fetch wrapper: same-origin JSON with the httpOnly session cookie.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function detailMessage(detail) {
  if (Array.isArray(detail)) {
    // FastAPI validation errors: show the first one in plain words.
    const first = detail[0] ?? {};
    const field = (first.loc ?? []).slice(-1)[0];
    return `${field ? `${field}: ` : ''}${(first.msg ?? 'invalid input').replace(/^Value error, /, '')}`;
  }
  return detail || 'Something went wrong';
}

export async function api(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, 'Cannot reach the server — check your connection.');
  }
  if (res.status === 401) window.dispatchEvent(new CustomEvent('utsav:unauthorized'));
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, detailMessage(data.detail));
  return data;
}
