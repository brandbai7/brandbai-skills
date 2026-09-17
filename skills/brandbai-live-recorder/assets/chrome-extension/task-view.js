/* Presentation only. Keep controls and keyboard focus stable across status updates. */
(() => {
  function key(node) {
    if (node.nodeType !== 1) return `node:${node.nodeType}`;
    return `${node.tagName}:${node.dataset.taskRole || node.id || node.className}`;
  }
  function reconcile(current, next) {
    if (current.nodeType !== 1) {
      if (current.nodeValue !== next.nodeValue) current.nodeValue = next.nodeValue;
      return;
    }
    for (const attr of [...current.attributes]) if (!next.hasAttribute(attr.name)) current.removeAttribute(attr.name);
    for (const attr of next.attributes) if (current.getAttribute(attr.name) !== attr.value) current.setAttribute(attr.name, attr.value);
    // This subtree has its own receipt renderer and buttons; never replace it with an empty slot.
    if (current.classList.contains('inline-delivery')) return;
    const unused = new Set(current.childNodes);
    let cursor = current.firstChild;
    for (const desired of [...next.childNodes]) {
      const found = [...unused].find(node => key(node) === key(desired));
      if (found) {
        unused.delete(found);
        if (found !== cursor) current.insertBefore(found, cursor);
        reconcile(found, desired);
        cursor = found.nextSibling;
      } else {
        current.insertBefore(desired, cursor);
      }
    }
    for (const node of unused) node.remove();
  }
  globalThis.BrandbaiTaskView = {
    patch(current, next) {
      const focused = current.contains(document.activeElement) ? document.activeElement : null;
      reconcile(current, next);
      if (focused?.isConnected && document.activeElement !== focused) focused.focus({preventScroll:true});
    }
  };
})();
