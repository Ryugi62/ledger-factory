// Tiny DOM helpers: element builder and message slots.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'testid') el.setAttribute('data-testid', v);
    else if (k === 'value') el.value = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

let uid = 0;
export const nextId = (prefix) => `${prefix}-${++uid}`;

// A message slot: the element with `testid` exists only while there is a message.
export function messageSlot(testid, kind) {
  const holder = h('div', { class: 'msg-slot', 'aria-live': 'polite' });
  return {
    el: holder,
    show(text) {
      holder.replaceChildren(h('p', { class: `msg msg-${kind}`, role: kind === 'error' ? 'alert' : 'status', testid }, text));
    },
    clear() { holder.replaceChildren(); },
  };
}

export const icon = (name) => h('span', { class: `icon icon-${name}`, 'aria-hidden': 'true' });
