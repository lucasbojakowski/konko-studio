const API_URL = "/api";

// helpers
const $ = (s, el=document) => el.querySelector(s);
const $$ = (s, el=document) => Array.from(el.querySelectorAll(s));

const api = async (p, opts={}) => {
  const res = await fetch(`${API_URL}${p}`, opts);
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = { error: text || "bad json" }; }
  if (!res.ok) throw new Error(data?.error || res.statusText);
  return data;
};

function toast(msg) {
  const t = document.createElement('div');
  t.className = 'fixed bottom-4 right-4 bg-neutral-900 text-neutral-100 px-3 py-2 rounded shadow';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2200);
}

function fileToFormData(file) {
  const fd = new FormData();
  fd.append('file', file);
  return fd;
}

async function uploadReference(file) {
  const res = await fetch(`${API_URL}/references`, { method: 'POST', body: fileToFormData(file) });
  if (!res.ok) throw new Error('upload failed');
  return res.json();
}

async function importReferenceUrl(url) {
  const fd = new FormData();
  fd.append('url', url);
  const res = await fetch(`${API_URL}/references`, { method: 'POST', body: fd });
  if (!res.ok) throw new Error('url import failed');
  return res.json();
}

export { $, $$, api, toast, uploadReference, importReferenceUrl };